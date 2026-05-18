# Phase-3c Pre-Cutover Daily-Probe Runbook (Tag-44)

**Authoritative source for the autonomous daily pre-cutover-probe
driver covering the ~3-week pre-KW-24-Cutover window
(2026-05-19 -> 2026-06-07).**

Anchor ADRs: ADR-0065 (Phase-3c cutover-plan),
ADR-0066 (Doppel-Welle KW-24/26/27 ordering),
ADR-0058 §Nachtrag (Mira-Hand-SSH-Authority).

Author: Reza Tehrani (Dev-Engineering-2), Sprint-Tag-44,
2026-05-18.

---

## 1. What this runbook covers

The Tag-43 Live-Demo orchestrator (PR #277,
`scripts/phase-3c/pre-cutover-probe-phase-live-demo.py`) is a
single-shot driver that runs all seven ADR-0066 Welle pre-cutover
probes in sandbox-stub mode and emits a per-Welle verdict plus a
Marathon-Readiness aggregate. The Tag-44 daily-probe-driver
(this runbook) promotes that single-shot tool into an
**autonomous trend tracker** that runs every morning at 06:00 UTC
across the pre-KW-24-cutover window.

Components shipped:

- `.github/workflows/phase-3c-pre-cutover-daily-probe.yml`
  -- the scheduled workflow.
- `scripts/observability/pre-cutover-daily-trend-analyzer.py`
  -- stdlib-only trend aggregator (daily mode + weekly-bilanz mode).
- `tests/observability/test_pre_cutover_daily_trend_analyzer.py`
  -- 23 hermetic tests.

---

## 2. Daily run cadence

| When | Trigger | Outputs |
|---|---|---|
| 06:00 UTC daily | `schedule: cron "0 6 * * *"` | Job-Summary + artifact `phase-3c-pre-cutover-daily-trend-<date>` (retention 30 days). |
| Operator-hand | `workflow_dispatch` with `today=yyyy-mm-dd` and `persist=true` | Same as scheduled run, plus state-file is committed by operator. |
| On push / PR touching the analyzer / live-demo / probe-scripts | path-filtered `push:` / `pull_request:` | Same as scheduled run. |

The workflow runs once per day at 06:00 UTC, one hour offset from the
Tag-42 Marathon-Dashboard's Monday-only run; the two are
complementary, not duplicates.

---

## 3. Outputs per run

The workflow produces six artifacts:

1. `out/live-demo-envelope.json` -- raw envelope from the Tag-43
   live-demo orchestrator. Contains seven per-Welle ProbeResults,
   the Marathon-Readiness aggregate, and the
   expected-vs-observed delta.
2. `out/live-demo-summary.md` -- the live-demo's own ASCII summary.
3. `out/trend-report.json` -- the Tag-44 analyzer's rollup
   (today_envelope + window history + change events).
4. `out/trend-report.md` -- the trend report Markdown (also
   appended verbatim to `$GITHUB_STEP_SUMMARY`).
5. `state/pre-cutover-daily-trend/<date>.json` -- the canonical
   per-day envelope. Stored under repo `state/` only when
   operator manually persists (see §5).
6. `state/notify-events.jsonl` -- append-only feed; one JSON
   object per non-lateral verdict change. Consumed by
   Mira-Hand-Sichtung for inbox triage.

---

## 4. Verdict semantics

Per-Welle verdicts (carried over from Reza Tag-41 probe contract):

| Verdict | Probe exit-code | Meaning |
|---|---|---|
| `GREEN` | 0 | All axes matched, cutover GO. |
| `CAUTION` | 1 | At least one yellow axis, operator review required. |
| `BLOCK` | 2 / 3 | At least one red axis, cutover NO-GO. |
| `NOT-EXEC` | 4 | Probe could not run (probe-script absent on this HEAD). |

Marathon-Readiness aggregate (mirrors `aggregate_marathon_readiness`
in the Tag-43 live-demo):

| Aggregate | Rule |
|---|---|
| `READY` | All seven Welles GREEN. |
| `CAUTION` | 1..2 CAUTION / NOT-EXEC, zero BLOCK. |
| `BLOCK` | Any BLOCK, OR 3+ CAUTION / NOT-EXEC. |
| `NOT-READY` | All seven NOT-EXEC. |

**Baseline (sandbox-stub on clean main):** `BLOCK`
(5 CAUTION + 1 GREEN + 1 BLOCK; Welle-7 IIA-1130 gate fires by
design). Any drift from that baseline is the trend signal.

---

## 5. Verdict-change classification

Day-over-day classification is by *verdict-rank* (higher = worse
posture):

| Rank | Per-Welle verdict | Aggregate |
|---|---|---|
| 0 | GREEN | READY |
| 1 | CAUTION | CAUTION |
| 2 | NOT-EXEC | BLOCK |
| 3 | BLOCK | NOT-READY |

Classification kinds:

- `STATUS-NEW` -- no envelope existed yesterday.
- `STATUS-LATERAL` -- same verdict (no change, dropped from notify-feed).
- `STATUS-DEGRADED` -- current rank > previous rank.
- `STATUS-IMPROVED` -- current rank < previous rank.

Only `STATUS-NEW` / `STATUS-DEGRADED` / `STATUS-IMPROVED` events
are written to `state/notify-events.jsonl`. The `STATUS-LATERAL`
steady-state is the no-news case.

---

## 6. Persistence policy (operator-hand)

Per AR-Direktive Tag-44 + ADR-0058, **scheduled CI does NOT push
state files to main.** The workflow's `permissions:` declares
`contents: read` only -- the runner cannot push even if asked.

To persist today's state into the repo:

```bash
gh workflow run phase-3c-pre-cutover-daily-probe \
  --ref main \
  -f today=2026-05-18 \
  -f persist=true \
  -f window_days=7

# Then download the artifact and commit by hand:
gh run download <run-id> --name phase-3c-pre-cutover-daily-trend-2026-05-18
git add state/pre-cutover-daily-trend/2026-05-18.json
git add state/notify-events.jsonl
git commit -m "ops(phase-3c): daily-probe state 2026-05-18"
```

Mira-Hand-only: the actual `git push` step is operator-authority
per ADR-0058 §Nachtrag.

---

## 7. Reading the trend report

The Job-Summary contains four panels:

1. **Today's per-Welle verdicts** -- a 1x7 table with today's
   per-Welle status.
2. **Trend (last N days)** -- an 8 x N grid; rows are Welle-1..7
   plus the aggregate row, columns are calendar days
   (oldest -> newest).
3. **Stability** -- per-Welle % of window-days matching the
   *latest* verdict. 100% means the welle stayed the same all
   week.
4. **Day-over-day changes** -- only non-lateral events. Empty
   when steady-state.

Sample interpretation:

- *All seven Welles stable + aggregate stable*: continue as-is.
- *Welle-7 STATUS-IMPROVED BLOCK -> GREEN*: operator-hand has
  staged the IIA-1130 pre-auditor-decision fixture; verify the
  improvement is real, not a stub regression.
- *Aggregate STATUS-DEGRADED CAUTION -> BLOCK*: triage the
  Welle that caused the degradation; if it's the same Welle
  that's been CAUTION/BLOCK for >2 days, escalate to Priya CTO.

---

## 8. Weekly bilanz mode (AR-Sitzung prep)

For the weekly AR-pre-cutover-review (Mira-Hand-Sichtung), run:

```bash
python3 scripts/observability/pre-cutover-daily-trend-analyzer.py \
  --state-dir state/pre-cutover-daily-trend \
  --mode weekly-bilanz \
  --today $(date -u +%Y-%m-%d) \
  --window-days 7 \
  --output-md reports/phase-3c/weekly-bilanz-$(date -u +%Y-%m-%d).md \
  --output-json reports/phase-3c/weekly-bilanz-$(date -u +%Y-%m-%d).json \
  --no-notify
```

The weekly-bilanz markdown contains:

- **Aggregate trajectory** -- per-day aggregate verdict + match flag.
- **Change-event tally** -- total + degraded + improved counts.
- **Per-Welle change density** -- which Welles flipped most often
  during the window.

---

## 9. Troubleshooting

### 9.1 All probes return `NOT-EXEC` on a clean main

The seven probe scripts must be present at
`scripts/phase-3c/welle-{1..7}-pre-cutover-probe.sh`. As of
Tag-44 all seven exist on main. If they go missing
(branch-protection bug, accidental revert), the aggregate
becomes `NOT-READY` and the workflow surfaces this loud in the
Job-Summary.

### 9.2 Demo orchestrator exits non-zero

The workflow tolerates non-zero exits from the live-demo (the
demo emits `BLOCK` exit-code 2 on the sandbox-stub baseline by
design). The analyzer parses the envelope regardless of the
demo's exit code; the workflow proceeds past
`steps.demo` with `set +e` -> capture -> `set -e`.

### 9.3 No state for previous days

A fresh `state/pre-cutover-daily-trend/` directory means every
welle shows `STATUS-NEW` on the first run. This is the
expected first-day behaviour. Subsequent runs build history.

### 9.4 Notify feed too noisy

If `state/notify-events.jsonl` is producing >50 events per day,
the demo is failing to classify lateral correctly -- check
that yesterday's state file is being read. The analyzer's
`detect_changes` function explicitly skips `STATUS-LATERAL`;
if you see lateral events in the feed there's a regression in
classify_change.

### 9.5 Window-days override

Operator can dispatch with `window_days=14` for two-week trend.
The analyzer defaults to 7; the workflow forwards
`inputs.window_days` to the analyzer's `--window-days` flag.

---

## 10. Anchors

- ADR-0065 (Phase-3c cutover-plan).
- ADR-0066 (Doppel-Welle KW-24/26/27 ordering).
- ADR-0058 §Nachtrag (Mira-Hand-SSH-Authority).
- Tag-41 (PR #267 Reza) -- Welle-1 Pre-Cutover-Probe reference.
- Tag-42 (PR #270 Tomas) -- Marathon-Dashboard CI workflow.
- Tag-42 (PR #271 Noa) -- Failure-Rate-Tracker.
- Tag-43 (PR #277 Reza) -- Pre-Cutover-Probe-Phase Live-Demo
  orchestrator.

-- Reza
