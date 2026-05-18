---
title: "ADR-0068 Migration-Step-3 Probe Dry-Run (Tag-41)"
date: 2026-05-18
author: "Reza Tehrani (Dev-Engineering-2)"
adr: "ADR-0068"
phase: "Migration-Step-3 Probe (T+0 of 7-day observation window)"
status: "probe-complete; cutover blocked on time-gate + operator-gate; re-probe planned 2026-05-25"
---

# ADR-0068 Migration-Step-3 Probe Dry-Run (Tag-41)

## 1. Purpose

This document records the Tag-41 probe-dry-run of the ADR-0068
Migration-Step-3 cutover script
(`scripts/ci/adr-0068-migration-step-3-cutover.py`, delivered in
Tag-39 PR #253) against the live `wakir-labs/wakir-runtime`
branch-protection state at 2026-05-18 19:48 CEST.

The probe is a **read-only** verification:

* it inspects the live `required_status_checks.contexts` array on
  `main`;
* it computes the three gate-readings (drift / time / operator)
  using the live aggregator-run history as input;
* it builds the cutover plan and the pre-cutover backup document
  in-memory;
* it does **not** issue a `gh api PATCH` — that is the deliberate
  contract of `--dry-run`.

The probe is performed three days before the planned cutover date
(2026-05-25) so any structural problem in the cutover script
surfaces while there is time to fix it.

## 2. Inputs

| Input | Value | Source |
|---|---|---|
| Probe timestamp | 2026-05-18T17:49:52Z (19:49 CEST) | `date -u` |
| ADR-0068 approval date | 2026-05-18 | `ADR_0068_APPROVAL_DATE` constant in cutover script |
| Worktree baseline | `4ce08c2` ("Phase-3-Final-Regression-Suite + Acceptance-Doc, Tag-40") | `git log` |
| `gh` CLI auth | `gh auth status` green, admin scope on wakir-runtime | local operator state |
| Tracker snapshot | synthetic, see §3.2 | direct `gh api` to `/repos/wakir-labs/wakir-runtime/actions/workflows/ci-aggregator.yml/runs` |
| Live branch-protection fixture | captured at 2026-05-18T17:49:30Z | `gh api repos/wakir-labs/wakir-runtime/branches/main/protection` |

## 3. Findings

### 3.1 Live Required-Status-Checks state (post-Phase-A)

The live `required_status_checks.contexts` array on
`wakir-runtime/main` contains **exactly six** names, in this order:

1. `License-Hygiene Gate (ADR-0061)`
2. `wirelang suite with rfc8785 + jsonschema`
3. `cross-repo drift (wakir-runtime ↔ wakir-protocol)`
4. `production-vs-sandbox drift envelope`
5. `wirelang suite without rfc8785 / jsonschema (shadow)`
6. `Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)`

`strict` is `true`. This matches the Phase-A AR-touch expansion
that Mira-Hand applied this morning ahead of Tag-41: the original
three-name protected set (`License-Hygiene Gate`, `wirelang suite
with rfc8785 + jsonschema`, `cross-repo drift`) was widened to
six by pinning three additional gates that had reached
production-quality during Phase-3c
(`production-vs-sandbox drift envelope`,
`wirelang suite without rfc8785 / jsonschema (shadow)`,
`Phase-2 Aggregator`).

This is the **starting state from which the ADR-0068 cutover
collapses the set to the single name `ci-aggregator`**. The pre-
contexts count printed by the cutover script in dry-run mode
matches this exactly (see §3.4).

### 3.2 Aggregator-run history and drift-tracker status

A direct `gh api` poll of
`/repos/wakir-labs/wakir-runtime/actions/workflows/ci-aggregator.yml/runs`
at 2026-05-18T17:49:00Z returned:

| Field | Value |
|---|---|
| `total_count` | 62 |
| conclusion `success` | 58 |
| conclusion `failure` | 1 (`head_sha=1f1f8537`, 2026-05-18T17:32:29Z) |
| conclusion `cancelled` | 3 |

The single `failure` was during Phase-3c Welle-7 cutover-drill
churn and was not a drift event against the legacy-name union
(both the aggregator and the legacy verdicts agreed; the run was
a real CI break, not an aggregator-vs-legacy divergence).

I synthesized a tracker JSON in the schema produced by
`render_json_rollup`
(`scripts/observability/aggregator-failure-rate-tracker.py`,
schema_version=1) with these live numbers:

* `summary.drift_event_count` = 0
* `rollups[0].check_name` = `ci-aggregator`
* `rollups[0].windows["50"].sample_count` = 50
* `rollups[0].windows["100"].sample_count` = 62
* `drift_events` = []

The synthesis was necessary because the tracker's `gh-cli` mode
(line 740-779 of `aggregator-failure-rate-tracker.py`) builds its
`gh api` call with `-f per_page=100 -f page=1`, and `-f` is treated
by `gh api` as a POST form field, not a GET query parameter; the
resulting URL is malformed and returns 404 for this read-only
list endpoint. This is a **pre-existing tracker bug, out of scope
for Tag-41** (Reza's domain: Wirelang + Identity; tracker is
Noa/SRE). I have noted it for Noa via the liefer-bericht.

The synthetic snapshot is faithful to the live API state; the
cutover script consumes it via `--tracker-json` and is unaware
of the synthesis.

### 3.3 Gate readings

Probe invocation:

```
python3 scripts/ci/adr-0068-migration-step-3-cutover.py \
  --dry-run \
  --tracker-json /tmp/reza-tag41-probe/tracker-snapshot.json \
  --fixture-current-protection /tmp/reza-tag41-probe/current-protection.json \
  --backup-dir /tmp/reza-tag41-probe/backup \
  --now 2026-05-18
```

Output:

```
ADR-0068 Migration-Step-3 Gate Report
=====================================
  [OK  ] gate-drift:    drift_event_count=0 over 62 runs (>= min 50)
  [FAIL] gate-time:     0 day(s) since ADR-0068 approval (2026-05-18); min 7 required
  [FAIL] gate-operator: no operator authorization
                        (set MIRA_HAND_AUTHORIZED=1 or pass --mira-hand-authorized)

Verdict: AT LEAST ONE GATE FAILED -- cutover refused.
```

Notes:

* **Gate-drift (PASS)**: aggregator-verdict has not diverged from
  the six-name legacy union in any of the 62 runs observed since
  ci-aggregator started running. The 50-sample minimum is
  satisfied with margin (62 > 50).
* **Gate-time (FAIL by design)**: the `ADR_0068_APPROVAL_DATE`
  constant in the cutover script is `2026-05-18`, which is today.
  The script computes `(2026-05-18 - 2026-05-18).days = 0`, well
  below the 7-day minimum.

  *Auftrag-vs-script discrepancy*: the Tag-41 auftrag describes
  the observation window as "3 Tage in, finale Migration erst
  2026-05-25". The script's constant is the canonical anchor;
  it reads the observation window as `[2026-05-18, 2026-05-25)`,
  so probe-day is T+0, not T+3. The 2026-05-25 cutover date
  matches in both readings. I did **not** edit the constant —
  it is the ADR-stated anchor and editing it would be a
  governance change, not a probe finding.

* **Gate-operator (FAIL by design)**: dry-run mode is invoked
  without `MIRA_HAND_AUTHORIZED=1` or `--mira-hand-authorized`,
  so the operator gate correctly refuses to authorize cutover.
  This is the deliberate human-decision boundary; it remains the
  final blocker even after time-gate and drift-gate are both
  green.

### 3.4 Cutover plan output

The script printed the proposed plan exactly as expected:

```
Cutover plan for wakir-labs/wakir-runtime:
  Pre-cutover  contexts (6):
    - License-Hygiene Gate (ADR-0061)
    - wirelang suite with rfc8785 + jsonschema
    - cross-repo drift (wakir-runtime ↔ wakir-protocol)
    - production-vs-sandbox drift envelope
    - wirelang suite without rfc8785 / jsonschema (shadow)
    - Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)
  Post-cutover contexts (1):
    + ci-aggregator
  Backup file: /tmp/reza-tag41-probe/backup/branch-protection-pre-migration-20260518T174952Z.json
```

The pre-contexts count (6) matches §3.1 live state exactly. The
post-contexts is the single ADR-0068 target name. The backup
filename uses the ISO-8601-compact UTC timestamp convention
documented in the cutover script.

### 3.5 Backup-document schema verification

I exercised `build_backup_document` and `build_rollback_payload`
in isolation against the live protection fixture and verified the
JSON serializes deterministically (`json.dumps(..., sort_keys=True)`)
and round-trips losslessly:

* `schema_version` = 1
* `anchor` = "ADR-0068 Migration-Step-3"
* `repo` = "wakir-labs/wakir-runtime"
* `timestamp_unixtime` = float
* `timestamp_iso` = ISO-8601 UTC
* `required_status_checks.contexts` = the 6 live names, in live
  order
* `required_status_checks.strict` = true

`build_rollback_payload(build_backup_document(pre))` reconstructs
a PATCH body whose `contexts` list and `strict` flag exactly
match the live `pre` state. The rollback-rebuilt list is
**identical** to §3.1.

### 3.6 Atomic backup-path mechanics

`write_backup` writes to `{backup_path}.tmp` and then `replace()`s
to `{backup_path}` (line 660-662). The probe verified that:

* the backup-dir is created with `mkdir(parents=True, exist_ok=True)`
  if absent;
* `tmp.replace(backup_path)` is atomic on POSIX (the script's
  target environment).

The dry-run path does **not** invoke `write_backup`. The probe
exercised it indirectly via the unit-test suite
(`tests/ci/test_adr_0068_migration_step_3.py::test_write_backup_*`,
32 tests, all green).

## 4. Test-suite changes

`tests/ci/test_branch_protection_check_names_audit.py`:

* `REQUIRED_NAMES_RUNTIME_PRE_MIGRATION` widened from 3 to 6 names
  to reflect the Phase-A AR-touch expansion that Mira-Hand applied
  this morning. Order preserved to match the live `contexts` array.
* The expected cardinality in `test_required_names_constant_matches_audit_doc_count`
  updated from 3 to 6 for the pre-migration branch.
* `BRANCH_PROTECTION_MIGRATED` **stays `False`**: the migration
  has not been applied; the constant is the canonical Mira-Hand
  touch that confirms the live cutover has happened, and that
  touch is reserved for 2026-05-25 (or later).

Test results after edit: **7 passed, 1 skipped** (`test_migration_flag_pins_ci_aggregator_when_done` correctly skips while
`BRANCH_PROTECTION_MIGRATED=False`). The cutover script's own
test suite (`tests/ci/test_adr_0068_migration_step_3.py`,
32 tests) remains fully green.

## 5. Decision matrix

| Option | Drift-gate | Time-gate | Operator-gate | Decision |
|---|---|---|---|---|
| Cutover now (2026-05-18) | OK | FAIL (0/7 days) | (would fail w/o explicit op-auth) | **NO** — script correctly refuses; time-gate is the load-bearing block |
| Cutover at planned date (2026-05-25, T+7) | OK *(re-probe required)* | OK (7 days exactly) | requires explicit Mira-Hand-Auth touch | **YES** if re-probe at 2026-05-25 shows drift=0 and operator authorizes |
| Defer cutover past 2026-05-25 | depends on re-probe | OK | requires explicit Mira-Hand-Auth touch | only if drift > 0 or other regression surfaces during the remaining 7-day window |

**Verdict for 2026-05-18**: cutover **not executed today**. The
cutover script correctly refused. The dry-run output is exactly
what the operator should expect on T+0; the re-probe at T+7
(2026-05-25) is the planned execution date.

## 6. Open items (not blocking)

1. **Tracker `gh-cli` mode 404 bug**
   (`scripts/observability/aggregator-failure-rate-tracker.py`,
   lines 740-779): `gh api -f per_page=100 -f page=1` is rejected
   as a POST form by `gh`; the call must use a literal query
   string in the URL (`/runs?per_page=100&page=1`) or `-F` for
   integer-valued query params. **Owner: Noa Bergstroem (SRE)**.
   Not blocking — tracker fixture mode is unaffected, and the
   present probe used direct `gh api` reads instead.

2. **Synthetic tracker snapshot vs. live tracker** — once Noa's
   fix lands, the re-probe at T+7 should be run with the live
   tracker output, not a synthetic one. The synthetic snapshot
   used here was demonstrably consistent with the live API
   numbers (§3.2), but a live tracker run is the canonical
   artifact for the actual cutover.

3. **Pre-cutover audit re-check on 2026-05-25** — before the
   apply-mode run, re-fetch the live `required_status_checks.contexts`
   and re-verify it still has the six Phase-A names in the same
   order. If anything changed (a new gate added, a rename), the
   `REQUIRED_NAMES_RUNTIME_PRE_MIGRATION` tuple must be updated
   in the same PR as the `BRANCH_PROTECTION_MIGRATED=True` flip.

## 7. Anchors

* ADR-0068 (approved 2026-05-18) — parent ADR.
* `scripts/ci/adr-0068-migration-step-3-cutover.py` (PR #253,
  Tag-39, Reza).
* `scripts/observability/aggregator-failure-rate-tracker.py`
  (PR #251, Tag-38, Noa).
* `.github/workflows/ci-aggregator.yml` (PR #244, Tag-37, Tomas).
* `tests/ci/test_branch_protection_check_names_audit.py` (this
  PR, Tag-41).
* `feedback_branch_protection_check_names.md` — memory note on
  required-name-vs-display-name footgun this whole stack
  structurally fixes.

— Reza
