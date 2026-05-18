# Welle-3 Day-0 Pipeline — Operator Runbook

**Script:** `scripts/welle-3-day-0-pipeline.sh`
**ADR:** ADR-0066 (Phase-3c Welle-3, `bridge_audit_writer` — KW 25 solo)
**Companion CI workflow:** `.github/workflows/phase-3c-welle-3-validation.yml` (PR #205)
**Audience:** Tomás (Engineering), Selin (Persona-Engine), Reza (WAT/Substrate),
operator-hand smoke runner during the Welle-3 cutover week.

## What this is

The Welle-3 cutover week (KW 25 in 2026) flips the persona-engine
default backend for `bridge_audit_writer` from Python to Rust.
ADR-0066 §Welle-Sequenz schedules Welle-3 **solo** — no parallel
partner — because the module being flipped IS the canonical
consistency oracle used by the earlier Welle-1/Welle-2 cutover
validations. Henrik (Internal Audit) flagged this in the ADR-0066
review:

> Consistency-Oracle-Selbst-Cutover-Risiko — once the persona engine's
> Rust backend takes over `bridge_audit_writer`, the very module that
> emits the BackendDecision audit envelopes is itself being swapped.
> Reading the consistency signal from the module that is mid-cutover
> is a circular oracle.

The CI workflow PR #205 mitigated this by swapping the bridge-audit-
roundtrip-e2e oracle for the Phase-2 Cross-Modul-Stress aggregator
(PR #197) as Welle-3 Step 4. This script does the same on the
operator side, with an explicit Phase Mi.5 that emits a `henrik_
caution_applied` flag in the acceptance-decision envelope.

The script is the **operator-side rehearsal + dispatch layer** that
runs the same five-phase sequence from a terminal so the team can
iterate locally and fire the live week from one command. It is the
Welle-3 sibling of `scripts/welle-1-day-0-pipeline.sh` (PR #218).

| Day  | Activity                                | Substrate                                                                          |
|------|-----------------------------------------|------------------------------------------------------------------------------------|
| Mo   | Local dry-run (gates + cutover)         | `phase-3c-trigger-gate-aggregator.py` + `phase-3c-cutover-dry-run.py --component bridge_audit_writer` |
| Mi   | CI Cutover-Validation run               | `phase-3c-welle-3-validation.yml` (PR #205)                                        |
| Mi.5 | **Henrik-Caution independent oracle**   | `doppelbetrieb-score-aggregator.py --mode=cross-modul-stress` (PR #197)            |
| Do   | Cross-Review (PRs + telemetry)          | `gh pr list` + `welle-3-telemetry-emitter` snapshot (PR #206) + observability JSONL |
| Fr   | Acceptance Decision                     | `cutover-acceptance-decision-welle-3.json` artifact                                |

## Component-aliasing — `bridge_audit_writer` vs. `anchor_emitter`

ADR-0065 §Welle-Sequenz spells the Welle-3 component as
`bridge_audit_writer`. The in-repo resolver / dry-run substrate uses
the short form `anchor_emitter`. Both spellings are accepted on the
CLI; the JSON envelopes record the long-form name verbatim so the
artifact stays operator-readable, and add a `component_resolver_alias`
field so the audit can follow the normalisation across systems.

```text
ADR-0065 long-form: bridge_audit_writer
in-repo short-form: anchor_emitter   (PHASE_3C_COMPONENT_ALIASES, PR #205)
```

## Dependencies

- `bash >= 4`
- `python3` (always required; powers JSON emit/read so jq is optional)
- `gh` (GitHub CLI; only required for the Mi phase when not in
  `--dry-run-all` mode, and for Do phase when collecting PR-review
  state)
- `git` (used implicitly by the called subprocess scripts)

## Quickstart

### Hermetic rehearsal (no network, no side-effects)

```bash
./scripts/welle-3-day-0-pipeline.sh --dry-run-all
```

Outcome: writes five phase-summary JSON artifacts plus a
`cutover-acceptance-decision-welle-3.json` into
`./.welle-3-day-0-artifacts/`. Exit-code 0 if every phase green,
1 if yellow, 2 if red.

### Single phase

```bash
./scripts/welle-3-day-0-pipeline.sh --phase mo  --dry-run-all
./scripts/welle-3-day-0-pipeline.sh --phase mi  --no-ci-wait
./scripts/welle-3-day-0-pipeline.sh --phase mi5 --dry-run-all
./scripts/welle-3-day-0-pipeline.sh --phase do
./scripts/welle-3-day-0-pipeline.sh --phase fr  --dry-run-all
```

Each phase reads its own inputs and writes its own
`phase-{mo,mi,mi5,do,fr}-summary.json`.

### Live week dispatch (Wednesday)

```bash
./scripts/welle-3-day-0-pipeline.sh --phase mi
```

This calls `gh workflow run phase-3c-welle-3-validation.yml`, locates
the dispatched run, and waits for completion. Verdict tracks the run
conclusion: success → green/0, failure → red/2. Add `--no-ci-wait` to
dispatch-and-walk-away (yields a yellow/1).

## Exit-code semantics

Every phase returns one of three codes. The overall run returns the
worst-of-all-phases:

| Code | Verdict          | Meaning                                                |
|------|------------------|--------------------------------------------------------|
| 0    | green            | Phase substrate green. Safe to proceed.                |
| 1    | yellow-proceed   | Soft signal (missing baseline / no-ci-wait / unknown). |
| 2    | red-block        | Hard fail. Do not advance the week.                    |

## Phase-by-phase reference

### Phase Mo — Monday Dry-Run

Invokes:

```
python3 scripts/phase-3c-trigger-gate-aggregator.py --repo-root … --json
python3 scripts/phase-3c-cutover-dry-run.py --component <bridge_audit_writer|anchor_emitter> --output …
```

The dry-run script normalises both spellings of the Welle-3 component
to `anchor_emitter` through `PHASE_3C_COMPONENT_ALIASES`. The pipeline
records both the operator-supplied name and the resolver-side alias
in the phase summary.

Reads `overall_status` from the gates envelope and `dry_run` from the
dry-run envelope. Red when gates report red, dry-run reports `blocked`,
or either process exits 2. Yellow on `yellow`/rc=1 from either.

Artifacts:

- `phase-mo-trigger-gates.json`
- `phase-mo-cutover-dry-run.json`
- `phase-mo-summary.json`

### Phase Mi — Wednesday CI-Cutover

Invokes `gh workflow run phase-3c-welle-3-validation.yml --ref main`
(opt-out with `--dry-run-all`), locates the most recent run, then
`gh run watch` (opt-out with `--no-ci-wait`). The verdict tracks the
GitHub Actions conclusion.

Artifact: `phase-mi-summary.json`.

### Phase Mi.5 — Henrik-Caution Independent Oracle (Welle-3-specific)

This phase exists **only** for Welle-3. It runs the Phase-2 Cross-
Modul-Stress aggregator
(`scripts/doppelbetrieb-score-aggregator.py --mode=cross-modul-stress`,
PR #197) as a consistency signal that is structurally independent
from `bridge_audit_writer`:

- `cross-modul-state-backing-lifecycle-state-machine`
- `cross-modul-subscribe-loop-recovery-workflow`
- `cross-modul-v907-verify-svid-workload-identity`

None of these axes use the bridge-audit-writer / anchor_emitter
substrate as their source-of-truth oracle, so they cannot be
"polluted" by the very module the cutover is flipping. This is
exactly the independence Henrik asked for in the ADR-0066
verification plan.

The summary records:

- `oracle`: `cross-modul-stress`
- `oracle_pr`: `PR-197`
- `independence_rationale`: textual marker for audit
- `threshold_pass`: `true` / `false` / `unknown`
- `henrik_caution_applied`: `true` iff `threshold_pass=true`

Verdict ladder:

| Aggregator outcome              | Verdict | exit_code | henrik_caution_applied |
|---------------------------------|---------|-----------|------------------------|
| `threshold_pass=true`, rc=0     | green   | 0         | true                   |
| `threshold_pass=false`, rc=1    | red     | 2         | false                  |
| script error (rc>=2)            | red     | 2         | false                  |
| envelope unparseable / missing  | yellow  | 1         | false                  |

The acceptance-decision envelope (Phase Fr) carries
`henrik_caution_applied` end-to-end so the operator and audit can
see at a glance whether the independent oracle confirmed Welle-3.

Artifacts:

- `phase-mi5-cross-modul-stress.json`
- `phase-mi5-summary.json`

### Phase Do — Thursday Cross-Review

Collects three signals:

1. **PR-review state** — `gh pr list … --search "welle-3 in:title,body"`
   tallies APPROVED / CHANGES_REQUESTED / commented counts.
2. **Welle-3-telemetry-emitter snapshot** (PR #206) — when
   `--telemetry-snapshot PATH` is supplied, the pipeline reads
   `divergence_red_flag`, `divergence_pct` and
   `consistency_score_pct` from the snapshot.
3. **WAT-telemetry snapshot** — counts lines and distinct days in
   `$WAKIR_PHASE_3C_OBS_BASELINE_PATH` (defaults to
   `state/backend-decision-observability/baseline.jsonl`).

Verdict:

- **Red** — at least one PR is `CHANGES_REQUESTED`, OR the live
  Welle-3 telemetry snapshot reports `divergence_red_flag=true`.
- **Yellow** — baseline JSONL missing (non-hermetic), OR zero
  approvals on >0 open PRs (non-hermetic).
- **Green** — at least one APPROVED, no CHANGES_REQUESTED, baseline
  present, no telemetry red-flag.

Artifact: `phase-do-summary.json`.

### Phase Fr — Friday Acceptance Decision

Reads the four earlier phase summaries (mo, mi, mi5, do) and emits
the canonical `cutover-acceptance-decision-welle-3.json`:

```jsonc
{
  "schema_version": 1,
  "adr": "ADR-0066",
  "welle": 3,
  "component": "bridge_audit_writer",
  "component_resolver_alias": "anchor_emitter",
  "generated_at": "<UTC ISO timestamp>",
  "decision": "go" | "go-with-caveats" | "no-go",
  "verdict":  "green" | "yellow" | "red",
  "exit_code": 0 | 1 | 2,
  "henrik_caution_applied": true | false,
  "phases": {
    "mo":  { "verdict": "...", "exit_code": ... },
    "mi":  { "verdict": "...", "exit_code": ... },
    "mi5": { "verdict": "...", "exit_code": ..., "oracle": "cross-modul-stress" },
    "do":  { "verdict": "...", "exit_code": ... }
  },
  "workdir": "<absolute path>"
}
```

This file is the artifact the operator commits/attaches to the
ADR-0066 Welle-3 PR-Bundle for AR sign-off. The
`henrik_caution_applied` field is the explicit signal that the
independent oracle confirmed Welle-3 — without it, AR sign-off is
not warranted regardless of the other phase verdicts.

## Common workflows

### Smoke before the cutover week

```bash
./scripts/welle-3-day-0-pipeline.sh --dry-run-all --component bridge_audit_writer
```

Should return rc=0 against a green-substrate main. If any phase yields
yellow or red, fix the substrate before the live Wednesday.

### Inspect a single artifact

The artifacts are plain JSON, so any of these works:

```bash
python3 -m json.tool .welle-3-day-0-artifacts/cutover-acceptance-decision-welle-3.json
jq . .welle-3-day-0-artifacts/cutover-acceptance-decision-welle-3.json
cat .welle-3-day-0-artifacts/phase-mi5-summary.json | python3 -m json.tool
```

### Live KW-25 dispatch — recommended order

```bash
# Monday 09:00 CEST — dry-run smoke
./scripts/welle-3-day-0-pipeline.sh --phase mo

# Wednesday 09:00 CEST — CI cutover-validation
./scripts/welle-3-day-0-pipeline.sh --phase mi

# Wednesday 14:00 CEST — independent oracle (Henrik-Caution)
./scripts/welle-3-day-0-pipeline.sh --phase mi5

# Thursday 14:00 CEST — emit live welle-3-telemetry snapshot first
python3 scripts/welle-3-telemetry-emitter.py \
    --out .welle-3-day-0-artifacts/welle-3-telemetry-snapshot.json

# Then feed it into Phase Do
./scripts/welle-3-day-0-pipeline.sh --phase do \
    --telemetry-snapshot .welle-3-day-0-artifacts/welle-3-telemetry-snapshot.json

# Friday 11:00 CEST — fuse the week
./scripts/welle-3-day-0-pipeline.sh --phase fr
```

The Friday `decision` field is the operator's go/no-go input for the
ADR-0066 Welle-3 Cutover-Acceptance review. AR sign-off for Welle-3
additionally requires `henrik_caution_applied=true` in the same
artifact.

## Troubleshooting

| Symptom                              | Likely cause                                                      | Action                                                                              |
|--------------------------------------|-------------------------------------------------------------------|-------------------------------------------------------------------------------------|
| `FATAL: missing dependency: python3` | Host lacks python3                                                | Install python3 >= 3.9                                                              |
| Phase Mo rc=2                        | Trigger-gate aggregator red OR dry-run blocked                    | Re-run components individually with `--json`, inspect gate-by-gate                  |
| Phase Mi rc=2 with "dispatch-failed" | `gh` not authenticated, wrong repo slug, or missing perms         | Run `gh auth status`, override `--gh-repo`                                          |
| Phase Mi rc=2 with "failure"         | The CI run itself failed                                          | Open the run in the GitHub UI; the workflow logs are authoritative                  |
| Phase Mi.5 rc=2                      | Cross-Modul-Stress aggregator reports `threshold_pass=false`      | Inspect `phase-mi5-cross-modul-stress.json` axis-by-axis; the failing axis blocks   |
| Phase Mi.5 rc=1 (yellow)             | Stress envelope unparseable / threshold field missing             | Re-run the aggregator directly; check `--out` permissions                            |
| Phase Do rc=1 (yellow)               | Observability baseline JSONL missing                              | Set `WAKIR_PHASE_3C_OBS_BASELINE_PATH` to the operator-staged file                  |
| Phase Do rc=2 with divergence flag   | Live `welle-3-telemetry-emitter` flagged `divergence_red_flag`    | The bridge-audit cutover is diverging in real-time — abort cutover, page Henrik     |
| Phase Fr rc=2                        | One of the four earlier phases red                                | Inspect `phases.{mo,mi,mi5,do}.verdict` in the decision JSON                        |
| Phase Fr `henrik_caution_applied=false` despite all-green | Mi.5 was skipped or yellow                            | Re-run `--phase mi5`; AR-sign-off requires the flag to be `true`                     |

## Related substrate

- `docs/operations/phase-3c-welle-3-runbook.md` — full Welle-3 ops
  procedure for the entire cutover week.
- `docs/operations/welle-1-day-0-pipeline-runbook.md` — Welle-1
  sibling (PR #218), four phases without the Henrik-Caution Mi.5.
- `docs/operations/welle-3-telemetry-runbook.md` — runbook for the
  live `welle-3-telemetry-emitter.py` (PR #206) whose snapshot Phase
  Do consumes.
- `docs/operations/phase-3c-trigger-gates.md` — semantics of the
  five trigger-gates this script's Mo phase aggregates.
- `docs/operations/phase-3c-cutover-runbook.md` — cross-week ADR-0065
  procedure, of which Welle-3 is the third instance.

## Versioning

The script exposes `--version`. Bump the inline `SCRIPT_VERSION`
constant when the JSON schema for the acceptance-decision changes;
the workflow consumer pins `schema_version: 1`.

— Kai
