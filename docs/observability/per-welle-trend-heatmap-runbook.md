# Per-Welle Trend-Heatmap Runbook (Tag-48)

**Owner:** Noa Bergstroem (SRE).
**Status:** Active 2026-05-19 -- 2026-06-07 (pre-cutover window).
**Anchors:** ADR-0065 Phase-3c cutover-plan, ADR-0066 Doppel-Welle
ordering, Reza Tag-44 PR #285 Daily-Trend-Analyzer, Noa Tag-46
PR #296 Mira-Notify chain, Noa Tag-47 PR #302 Alert-Bridge.

## Purpose

The Tag-48 Per-Welle Trend-Heatmap is the **visualisation layer**
sitting on top of the Tag-44 Daily-Trend-Analyzer. It renders an
at-a-glance posture surface so the operator can scan the
seven-Welle verdict-trend in three seconds during the daily
pre-cutover huddle.

The heatmap is *additive*: it does not replace the analyzer's
markdown trend-report, the Tag-46 Mira-Notify chain, or the
Tag-47 Alert-Bridge. It is a different view of the same data,
optimised for posture-at-a-glance.

## Inputs

* `state/pre-cutover-daily-trend/yyyy-mm-dd.json` -- the daily
  envelopes persisted by `scripts/observability/pre-cutover-daily-trend-analyzer.py`
  (Reza Tag-44 PR #285).
* Each envelope contains:
  * `date_iso` -- snapshot date.
  * `aggregate` -- READY / CAUTION / BLOCK / NOT-READY.
  * `per_welle` -- per-Welle verdict map (1..7).

The heatmap also accepts the upstream live-demo shape
(`started_at_utc` + `probes[]`) for robustness, but the daily
workflow always feeds it the analyzer's persisted shape.

## Outputs

| Output | Path | Consumer |
|---|---|---|
| ASCII grid | stdout or `--output-ascii` | Operator console |
| Markdown table | `--output-md` | `$GITHUB_STEP_SUMMARY`, AR-Sitzung-Review |
| JSON envelope | `--output-json` | `state/per-welle-heatmap/yyyy-mm-dd.json`, Grafana ingest |

## CLI usage

```bash
# Daily morning render (no arguments -> prints ASCII for the operator).
python3 scripts/observability/per-welle-trend-heatmap.py \
  --state-dir state/pre-cutover-daily-trend \
  --today 2026-05-19 \
  --window-days 7

# CI / workflow render (writes all three output forms).
python3 scripts/observability/per-welle-trend-heatmap.py \
  --state-dir state/pre-cutover-daily-trend \
  --today 2026-05-19 \
  --window-days 7 \
  --output-json state/per-welle-heatmap/2026-05-19.json \
  --output-md   state/per-welle-heatmap/2026-05-19.md \
  --output-ascii state/per-welle-heatmap/2026-05-19.txt
```

## Glyph legend

| Glyph | Meaning | Color bucket |
|---|---|---|
| `G` | GREEN (per-Welle healthy) | green |
| `C` | CAUTION (per-Welle yellow) | yellow |
| `N` | NOT-EXEC (probe skipped) | grey |
| `B` | BLOCK (per-Welle red) | red |
| `R` | READY (aggregate healthy) | green |
| `X` | NOT-READY (aggregate red) | red |
| `.` | MISSING (no snapshot that day) | transparent |

The per-Welle glyph namespace (`G/C/N/B`) is intentionally
disjoint from the aggregate glyph namespace (`R/X`) so the
operator can tell at a glance whether a green cell is a per-Welle
verdict or the aggregate flipping to READY.

## Sandbox-stub baseline (Phase-3c)

The pre-cutover-probe phase runs in `--dry-run` /
`WAKIR_SSH_BIN=true` sandbox-stub mode through the whole
~3-week pre-cutover window. The expected baseline heatmap is:

```
welle-1   C C C C C C C
welle-2   C C C C C C C
welle-3   C C C C C C C
welle-4   C C C C C C C
welle-5   C C C C C C C
welle-6   G G G G G G G
welle-7   B B B B B B B
AGG       B B B B B B B
```

Any drift from this shape (e.g. a Welle-4 row flipping to `B`,
or the AGG row flipping to `R`) is a signal that probe-script
structural-health has changed and warrants Mira-Hand-Sichtung.

The Tag-46 Mira-Notify chain (PR #296) is the operator-inbox
feed for these changes; the heatmap is the at-a-glance view of
the same signal.

## Grafana dashboard

UID: `wakir-per-welle-trend-heatmap`
File: `dashboards/per-welle-trend-heatmap.json`

Panels:

1. **Per-Welle Verdict Heatmap (state-timeline)** -- the primary
   surface; rows = welle-1..7 + aggregate, columns = days in
   window, cell color = verdict bucket.
2. **Days BLOCK in window (aggregate)** -- baseline indicator.
3. **Missing-day count in window** -- daily-probe workflow
   liveness indicator.
4. **Per-Welle stability (table)** -- count of days matching the
   most-recent verdict per row.

The dashboard reads from the same Prometheus textfile-collector
gauges the existing Tag-30/31/32 welle-status dashboard does
(`persona_engine_per_welle_heatmap_*`). The emitter that
populates those gauges from the JSON envelope is a separate
Tag-49 follow-up (out of scope for Tag-48 visualisation-only).

## Failure modes

| Symptom | Cause | Mitigation |
|---|---|---|
| All-`.` heatmap | `state/pre-cutover-daily-trend/` empty or workflow not running | Check `phase-3c-pre-cutover-daily-probe.yml` job status; manually invoke daily-probe-driver if needed |
| Heatmap renders but Grafana panel empty | Tag-49 emitter not yet shipped, or textfile-collector path misconfigured | This is expected until Tag-49; the JSON envelope is the canonical output |
| Heatmap shows unexpected `G` on Welle-7 | Probe-script structural drift OR live-VM accidentally targeted | Inspect today's daily-trend-analyzer markdown; cross-check with Mira-Notify feed and Alert-Bridge events |

## Hermetic tests

`tests/observability/test_per_welle_trend_heatmap.py` covers
the renderer's pure-function surface (19 tests). The test
suite is stdlib + pytest only; no network, no podman, no
live VM. Run with:

```bash
python3 -m pytest tests/observability/test_per_welle_trend_heatmap.py -v
```

---

_Runbook authored by Noa Bergstroem (SRE), Tag-48, 2026-05-19._
