# Welle-1 Day-0 Pipeline — Operator Runbook

**Script:** `scripts/welle-1-day-0-pipeline.sh`
**ADR:** ADR-0066 (Phase-3c Welle-1, `v907_verify`)
**Companion CI workflow:** `.github/workflows/phase-3c-welle-1-validation.yml`
**Audience:** Tomás (Engineering), Selin (Persona-Engine), Reza (WAT/Substrate),
operator-hand smoke runner during Welle-1 cutover week.

## What this is

The Welle-1 cutover week (KW 24-25 in 2026) flips the persona-engine
default backend for `v907_verify` from Python to Rust. ADR-0066
§Verifikations-Plan lays out a four-day sequence:

| Day | Activity                            | Substrate                                                          |
|-----|-------------------------------------|--------------------------------------------------------------------|
| Mo  | Local dry-run (gates + cutover)     | `phase-3c-trigger-gate-aggregator.py` + `phase-3c-cutover-dry-run.py` |
| Mi  | CI Cutover-Validation run           | `phase-3c-welle-1-validation.yml`                                  |
| Do  | Cross-Review (PRs + WAT telemetry)  | `gh pr list` + observability baseline JSONL                        |
| Fr  | Acceptance Decision                 | `cutover-acceptance-decision.json` artifact                        |

The CI workflow is the canonical record. This script is the
**operator-side rehearsal + dispatch layer** that runs the same four-
phase sequence from a terminal so the team can iterate locally and
fire the live week from one command.

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
./scripts/welle-1-day-0-pipeline.sh --dry-run-all
```

Outcome: writes four phase-summary JSON artifacts plus a
`cutover-acceptance-decision.json` into `./.welle-1-day-0-artifacts/`.
Exit-code 0 if every phase green, 1 if yellow, 2 if red.

### Single phase

```bash
./scripts/welle-1-day-0-pipeline.sh --phase mo --dry-run-all
./scripts/welle-1-day-0-pipeline.sh --phase mi --no-ci-wait
./scripts/welle-1-day-0-pipeline.sh --phase do
./scripts/welle-1-day-0-pipeline.sh --phase fr --dry-run-all
```

Each phase reads its own inputs and writes its own `phase-{mo,mi,do,fr}-summary.json`.

### Live week dispatch (Wednesday)

```bash
./scripts/welle-1-day-0-pipeline.sh --phase mi
```

This calls `gh workflow run phase-3c-welle-1-validation.yml`, locates
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
python3 scripts/phase-3c-cutover-dry-run.py --component <C> --output …
```

Reads `overall_status` from the gates envelope and `dry_run` from the
dry-run envelope. Red when gates report red, dry-run reports `blocked`,
or either process exits 2. Yellow on `yellow`/rc=1 from either.

Artifacts:

- `phase-mo-trigger-gates.json`
- `phase-mo-cutover-dry-run.json`
- `phase-mo-summary.json`

### Phase Mi — Wednesday CI-Cutover

Invokes `gh workflow run phase-3c-welle-1-validation.yml --ref main`
(opt-out with `--dry-run-all`), locates the most recent run, then
`gh run watch` (opt-out with `--no-ci-wait`). The verdict tracks the
GitHub Actions conclusion.

Artifact: `phase-mi-summary.json`.

### Phase Do — Thursday Cross-Review

Collects two signals:

1. **PR-review state** — `gh pr list … --search "welle-1 in:title,body"`
   tallies APPROVED / CHANGES_REQUESTED / commented counts.
2. **WAT-telemetry snapshot** — counts lines and distinct days in
   `$WAKIR_PHASE_3C_OBS_BASELINE_PATH` (defaults to
   `state/backend-decision-observability/baseline.jsonl`).

Verdict:

- Red — at least one PR is `CHANGES_REQUESTED`.
- Yellow — baseline JSONL missing, OR zero approvals on >0 open PRs.
- Green — at least one APPROVED, no CHANGES_REQUESTED, baseline present.

Artifact: `phase-do-summary.json`.

### Phase Fr — Friday Acceptance Decision

Reads the three earlier phase summaries and emits the canonical
`cutover-acceptance-decision.json`:

```jsonc
{
  "schema_version": 1,
  "adr": "ADR-0066",
  "welle": 1,
  "component": "v907_verify",
  "generated_at": "<UTC ISO timestamp>",
  "decision": "go" | "go-with-caveats" | "no-go",
  "verdict":  "green" | "yellow" | "red",
  "exit_code": 0 | 1 | 2,
  "phases": {
    "mo": { "verdict": "...", "exit_code": ... },
    "mi": { "verdict": "...", "exit_code": ... },
    "do": { "verdict": "...", "exit_code": ... }
  },
  "workdir": "<absolute path>"
}
```

This file is the artifact the operator commits/attaches to the
ADR-0066 Welle-1 PR-Bundle for AR sign-off.

## Common workflows

### Smoke before each cutover week

```bash
./scripts/welle-1-day-0-pipeline.sh --dry-run-all --component v907_verify
```

Should return rc=0 against a green-substrate main. If any phase yields
yellow or red, fix the substrate before the live Wednesday.

### Inspect a single artifact

The artifacts are plain JSON, so any of these works:

```bash
python3 -m json.tool .welle-1-day-0-artifacts/cutover-acceptance-decision.json
jq . .welle-1-day-0-artifacts/cutover-acceptance-decision.json
cat .welle-1-day-0-artifacts/phase-mo-summary.json | python3 -m json.tool
```

### Live Wednesday dispatch + Friday acceptance

```bash
# Wednesday 09:00 CEST
./scripts/welle-1-day-0-pipeline.sh --phase mi

# Thursday 14:00 CEST (after manual cross-review session)
./scripts/welle-1-day-0-pipeline.sh --phase do

# Friday 11:00 CEST — fuse the week
./scripts/welle-1-day-0-pipeline.sh --phase fr
```

The Friday `decision` field is the operator's go/no-go input for the
ADR-0066 Welle-1 Cutover-Acceptance review.

## Troubleshooting

| Symptom                              | Likely cause                                              | Action                                                                 |
|--------------------------------------|-----------------------------------------------------------|------------------------------------------------------------------------|
| `FATAL: missing dependency: python3` | Host lacks python3                                        | Install python3 >= 3.9                                                 |
| Phase Mo rc=2                        | Trigger-gate aggregator red OR dry-run blocked            | Re-run components individually with `--json`, inspect gate-by-gate     |
| Phase Mi rc=2 with "dispatch-failed" | `gh` not authenticated, wrong repo slug, or missing perms | Run `gh auth status`, override `--gh-repo`                             |
| Phase Mi rc=2 with "failure"         | The CI run itself failed                                  | Open the run in the GitHub UI; the workflow logs are authoritative     |
| Phase Do rc=1 (yellow)               | Observability baseline JSONL missing                      | Set `WAKIR_PHASE_3C_OBS_BASELINE_PATH` to the operator-staged file     |
| Phase Fr rc=2                        | One of the three earlier phases red                       | Inspect `phases.{mo,mi,do}.verdict` in the decision JSON                |

## Related substrate

- `docs/operations/phase-3c-welle-1-runbook.md` — full Welle-1 ops
  procedure for the entire cutover week.
- `docs/operations/phase-3c-trigger-gates.md` — semantics of the
  five trigger-gates this script's Mo phase aggregates.
- `docs/operations/phase-3c-cutover-runbook.md` — cross-week ADR-0065
  procedure, of which Welle-1 is the first instance.

## Versioning

The script exposes `--version`. Bump the inline `SCRIPT_VERSION`
constant when the JSON schema for the acceptance-decision changes;
the workflow consumer pins `schema_version: 1`.
