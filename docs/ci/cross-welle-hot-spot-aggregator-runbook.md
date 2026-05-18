# Cross-Welle Hot-Spot Aggregator -- Runbook

**Status:** active (Tag-49, 2026-05-19)
**Owner:** Tomas (Dev-Engineering, Matrix-Lead)
**Spec source:** Henrik Tag-44 Pre-Mortem
  (`agents-workspaces/mira/inbox/2026-05-18-henrik-tag-44-pre-mortem-done.md`),
  Henrik Tag-45 Mitigation-Map
  (`agents-workspaces/mira/inbox/2026-05-18-tag-45-mitigation-map-deep-dives.md`)
**Workflow:** `.github/workflows/cross-welle-hot-spot-aggregator.yml`
**Aggregator:** `tooling/ci/cross_welle_hot_spot_aggregator.py`
**Tests:** `tests/ci/test_cross_welle_hot_spot_aggregator.py`

## 1. Why this aggregator exists

Tag-45 (PR #288) and Tag-48 (PR #312) shipped per-welle hot-spot
probes for Welle-3, Welle-4, Welle-5, Welle-6, Welle-7. Each probe
answers the question

> "Is Welle-N standing on its four hot-spot axes today?"

but none of them answer the cross-welle marathon question

> "Across all seven cutover Wellen, what is the marathon hot-spot
> picture for KW-25 .. KW-27?"

The Tag-44 all-seven daily trend probe
(`phase-3c-pre-cutover-daily-probe.yml`, Reza) tracks a per-welle
green / yellow / red trend signal but does **not** compose the
per-welle hot-spot envelopes (with their `cross_welle_propagation`
blocks) into a marathon rollup. This aggregator is that rollup.

It runs **30 min after** the per-welle Welle-3 hot-spot probe so
that the per-welle envelopes for that day are guaranteed to be
present in the trend dirs before the rollup starts.

## 2. Inputs

The aggregator reads the five per-welle trend directories:

* `state/welle-3-hot-spot-trend/<yyyy-mm-dd>.json`
* `state/welle-4-hot-spot-trend/<yyyy-mm-dd>.json`
* `state/welle-5-hot-spot-trend/<yyyy-mm-dd>.json`
* `state/welle-6-hot-spot-trend/<yyyy-mm-dd>.json`
* `state/welle-7-hot-spot-trend/<yyyy-mm-dd>.json`

For each welle it picks the newest envelope within
`--max-age-days` (default 2 days) of `--today` (default UTC today).

Welle-1 (`v907_verify`, cutover complete Tag-34 PR #230) and
Welle-2 (`svid_workload_identity`, cutover complete Tag-35 PR #234)
are not probed daily. Their slots are recorded as `POST-CUTOVER`
when no envelope is found -- **not** as `UNKNOWN`, which is reserved
for missing telemetry on a live welle.

## 3. The five outputs

### 3.1 Per-welle slot list

One slot per welle in `{1..7}`:

| Field                  | Meaning                                          |
|------------------------|--------------------------------------------------|
| `welle`                | welle number                                     |
| `verdict`              | `CLEAR` / `CAUTION` / `BLOCK` / `UNKNOWN` / `POST-CUTOVER` |
| `dated_at`             | ISO date of the envelope used (null when missing) |
| `counts`               | per-welle `{green,yellow,red}` check counts      |
| `failed_checks`        | per-welle failed-check names                     |
| `propagation_targets`  | `pre_conditional_blocked` list from the welle    |
| `envelope_source`      | `workflow` field of the source envelope          |

### 3.2 Marathon verdict (one of `CLEAR`, `CAUTION`, `BLOCK`)

Decision rule across live-welle slots (Welle-3..7):

* `CLEAR` -- all five live slots `CLEAR`.
* `CAUTION` -- any `CAUTION`, no `BLOCK`, no `UNKNOWN`.
* `BLOCK` -- any `BLOCK` OR any `UNKNOWN` (loud-failure on missing
  telemetry).

`POST-CUTOVER` slots are excluded from the verdict.

### 3.3 Cascade fan-out

The per-welle `cross_welle_propagation.pre_conditional_blocked`
lists are transitively closed. For example a Welle-3 BLOCK
propagates to `{4, 5, 7}`; if Welle-5 also has propagation
edges into `{7}` those are reached transitively.

The envelope records two related fields:

* `cascade_fan_out` -- union of all wellen reached by any BLOCK
  seed's transitive closure.
* `cascade_fan_out_per_seed` -- per BLOCK seed welle, the list of
  wellen it transitively reaches.

### 3.4 Top hot-spot ranking

The five live slots are sorted by:

1. `(red + unknown-bonus)` descending (most reds = most severe;
   `UNKNOWN` gets a +1 bonus so it sorts above same-red-count
   `BLOCK` slots -- stale telemetry is the most urgent to surface)
2. `yellow` count descending
3. propagation fan-out size descending
4. welle number ascending

The top-3 are surfaced on the envelope's `top_hot_spots` and in the
Job-Summary.

### 3.5 Notify-events feed

When the marathon verdict is `BLOCK` (every run) or transitions
into `CAUTION` (vs `--prev-verdict`), a JSON-line is appended to
`state/notify-events.jsonl`:

```json
{
  "schema_version": 1,
  "kind": "cross-welle-hot-spot-aggregator",
  "emitted_at_utc": "...",
  "today": "...",
  "verdict": "BLOCK",
  "live_welle_counts": {...},
  "cascade_fan_out": [4, 5, 7],
  "top_hot_spots": [...],
  "github_run_id": "...",
  "github_sha": "..."
}
```

A stable `CAUTION` does **not** spam the feed (the rule fires on
the transition only).

## 4. Trigger surface

* `schedule: cron "0 7 * * *"` -- daily 07:00 UTC.
* `workflow_dispatch` -- with optional `today` override and
  `persist` flag for back-fill / replay.
* `push` (path-filtered) -- changes to the aggregator / workflow /
  tests / runbook re-run the rollup so test loops surface breakage
  immediately.
* `pull_request` (path-filtered) -- same filter for dry-run before
  merge.

## 5. Not a required status check

Per `feedback_branch_protection_check_names.md` this workflow
tracks a calendar-window cross-welle hot-spot trend, not individual
PR acceptance. It is **not** listed as a required status check on
PRs.

## 6. Operator-hand back-fill

```bash
gh workflow run cross-welle-hot-spot-aggregator.yml \
  --field today=2026-05-21 \
  --field persist=false
```

The `persist=true` path is reserved for state-file staging; per
ADR-0058 + AR-Direktive Tag-44 the actual push is operator-hand
(runner has `contents: read` only).

## 7. Hermetic posture

Strict hermetic. stdlib + PyYAML only (PyYAML in test path). No
podman / cosign / live-VM. No network. The Python aggregator does
no subprocess calls; the upstream per-welle envelopes are computed
by the five per-welle workflows independently.

## 8. Failure-mode interpretation

| Marathon verdict | What it means                                                 | Next step                                 |
|------------------|---------------------------------------------------------------|-------------------------------------------|
| `CLEAR`          | All five live wellen `CLEAR`. Marathon is on-track.           | No action.                                |
| `CAUTION`        | One or more live wellen `CAUTION`. No reds, no missing data.  | Deep-dive top-hot-spot welle, no halt.    |
| `BLOCK`          | Any live welle `BLOCK` OR any live welle `UNKNOWN` (stale).   | Mira-Hand Sichtung + cutover-window halt. |

`UNKNOWN` always escalates to `BLOCK` to enforce loud-failure on
missing telemetry: a silent gap in the per-welle probe pipeline
must not be confused with `CLEAR`.

## 9. Cross-references

* Henrik Tag-44 Pre-Mortem (the structural risk-matrix that motivates
  the per-welle propagation edges)
* Henrik Tag-45 Mitigation-Map (the Welle-4/5/6/7 Pre-Mortem-Folge)
* `phase-3c-welle-3-hot-spot-probe.yml` (Tag-45 PR #288)
* `phase-3c-welle-{4,5,6,7}-hot-spot-probe.yml` (Tag-48 PR #312)
* `phase-3c-pre-cutover-daily-probe.yml` (Reza Tag-44 all-seven
  trend tracker)
