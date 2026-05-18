# Phase-3 Final Bilanz — Output Schema

| Field | Value |
|---|---|
| Document type | Output schema reference |
| Schema version | `1.0.0` |
| Generator | `scripts/observability/phase-3-final-bilanz-generator.py` (PR #280, Tag-43) |
| Validator | `scripts/observability/bilanz-output-schema-validator.py` (Tag-44) |
| Owner | Noa (SRE) |
| Last update | 2026-05-18 (Tag-44 validation pass) |

## 1. Purpose

This document is the contract reference for the JSON output of the
Phase-3 Final Bilanz Generator. Downstream consumers (Henrik Internal
Audit, the Phase-4 pre-substanz-plan generator, the workflow-hook
artefact uploader) rely on the shape described here. Any change must
bump the schema version and update both the generator and the
validator in lock-step.

The validator is stdlib-only (no `jsonschema` package dependency) so
it runs on the sandbox lane as well as the production lane.

## 2. Top-Level Shape

```
{
  "schema_version": "1.0.0",
  "generated_at": "<ISO-8601 UTC, Z-suffix>",
  "executive_summary": { ... },
  "per_welle": { "<welle-id>": { ... }, ... },
  "aggregator_history_rollup": { ... },
  "complete_marker_validation": { ... },
  "audit_aggregate": { ... },
  "phase_4_followups": [ "<string>", ... ]
}
```

Every top-level key is required. `schema_version` must start with
`1.` (the validator handles 1.x; 2.x will require a new validator
branch).

`generated_at` is checked as a cheap ISO-8601 shape (must contain `T`
and end with `Z` or contain `+`). The full parse is deliberately not
performed in the validator so the schema check stays stdlib-only and
sandbox-safe.

## 3. Executive Summary

```
executive_summary: {
  "wellen_total":               <int, expected 7>,
  "wellen_with_sign_off":       <int, 0..7>,
  "marathon_last_update":       <ISO-8601 str>,
  "aggregator_runs_total":      <int, >= 0>,
  "aggregator_failure_rate":    <float in [0,1] | null>,
  "drift_status_counts":        { "<status>": <int>, ... },
  "latency_status_counts":      { "<status>": <int>, ... },
  "complete_marker_is_complete": <bool>,
  "audit_aggregate_ok":          <bool>
}
```

Status enums:

- `drift_status_counts` keys: `OK | WARN | BREACH | NO_DATA`.
- `latency_status_counts` keys: `OK | WARN | BREACH | NO_DATA | NO_BUDGET`.

Counts are non-negative ints. The validator rejects any unknown
status key (cheap guard against rename drift).

## 4. Per-Welle

```
per_welle: {
  "welle-1-v907-verify": {
    "short":                <str, e.g. "W1 v907-verify">,
    "marathon": {
      "cutover_runs_total":             <int>,
      "cutover_runs_rust":              <int>,
      "cutover_runs_python_fallback":   <int>,
      "rust_share":                     <float | null>,
      "decision_latency_ms_p50":        <float | null>,
      "decision_latency_ms_p95":        <float | null>,
      "decision_latency_ms_p99":        <float | null>,
      "decision_latency_ms_n":          <int>,
      "last_sample_at":                 <str>
    },
    "backend_snapshots": { ... },
    "drift": {
      "drift_pct_samples_n":  <int>,
      "drift_pct_p50":        <float | null>,
      "drift_pct_p95":        <float | null>,
      "drift_pct_max":        <float | null>,
      "drift_status":         "OK | WARN | BREACH | NO_DATA",
      "bucket_count":         <int>
    },
    "sign_off":             <object | null>,
    "latency_status":       "OK | WARN | BREACH | NO_DATA | NO_BUDGET",
    "latency_budget_ms":    <int, > 0>
  },
  ...
}
```

Welle keys are the canonical seven Phase-3 welle-ids
(`welle-1-v907-verify` … `welle-7-recovery-workflow`). The validator
rejects any unknown welle-id (guard against typo drift in downstream
authors).

A welle that has not started yet still produces a per-welle entry
with zero counts and `null` percentiles. The validator accepts
`null` for every percentile field.

## 5. Aggregator History Rollup

```
aggregator_history_rollup: {
  "runs_total":                   <int, >= 0>,
  "runs_success":                 <int, >= 0>,
  "runs_failure":                 <int, >= 0>,
  "failure_rate":                 <float | null>,
  "wait_loop_p50_s":              <float | null>,
  "wait_loop_p95_s":              <float | null>,
  "wait_loop_p99_s":              <float | null>,
  "sub_workflow_failure_buckets": { "<sub-workflow name>": <int>, ... }
}
```

`sub_workflow_failure_buckets` keys are GitHub-Actions job-display-names
(matching the Required-Status-Check names in branch-protection).
Counts are non-negative ints.

## 6. Complete Marker Validation

```
complete_marker_validation: {
  "present":             <bool>,
  "status":              "COMPLETE" | <other-str> | null,
  "is_complete":         <bool>,
  "completed_at":        <str | null>,
  "wellen_complete":     <int | null>,
  "approver":            <str | null>,
  "evidence_refs":       [ "<path-str>", ... ],
  "validation_errors":   [ "<error-token>", ... ]
}
```

Validation errors are short identifier tokens, not free-form prose;
this keeps the downstream grep-stability high. Known tokens:

- `marker_file_missing`
- `status_not_complete:<repr>`
- `wellen_complete_expected_7_got_<repr>`
- `completed_at_missing`
- `approver_missing`

## 7. Audit Aggregate

```
audit_aggregate: {
  "by_welle":           { "<welle-id>": { ... per-welle sign-off ... } },
  "aggregate_audit_ok": <bool>,
  "total_findings":     <int, >= 0>,
  "total_exceptions":   <int, >= 0>,
  "missing_sign_offs":  [ "<welle-id>", ... ]
}
```

`aggregate_audit_ok` is `true` iff every welle has a sign-off file
**and** every sign-off has `audit_ok: true` **and** there are no
unsigned wellen.

## 8. Phase-4 Follow-Ups

```
phase_4_followups: [ "<str>", ... ]
```

The list is **never empty**: when no follow-ups are detected the
generator emits a single placeholder line beginning with
`No outstanding follow-ups detected`. The validator enforces the
non-empty invariant so downstream `iter` consumers never need a
truthiness guard.

Follow-up lines are free-form prose. Stable substrings consumers may
rely on:

- `latency p95 BREACH` / `latency p95 WARN`
- `drift BREACH` / `drift WARN`
- `sign-off MISSING` (paired with the welle short-name, e.g. `W7 recovery-workflow`)
- `Phase-3-COMPLETE-marker not valid`

## 9. Versioning

| Schema version | Validator branch | Status |
|---|---|---|
| `1.0.0` | `validate_bilanz_dict` (Tag-44) | current |

Schema changes that **add** keys without altering existing semantics
remain `1.x`. Any change that **renames**, **removes**, or
**type-flips** an existing key must increment the major version.
The validator's `unsupported major version` error catches consumers
running against a newer generator without an updated validator.

## 10. Validator Usage

Library form (Python):

```python
from scripts.observability.bilanz_output_schema_validator import (
    validate_bilanz_dict,
)
errors = validate_bilanz_dict(json.load(open("reports/phase-3-marathon-bilanz.json")))
assert errors == [], errors
```

The script filename contains hyphens; the hermetic tests load it via
`importlib.util.spec_from_file_location` (see
`tests/observability/test_bilanz_generator_validation_runs.py` for
the pattern).

CLI form:

```
python3 scripts/observability/bilanz-output-schema-validator.py \
    reports/phase-3-marathon-bilanz.json [--quiet]
```

Exit codes:

- `0` — bilanz matches the schema.
- `1` — validation failure; error lines printed to stderr.
- `2` — file missing or JSON-parse error.

## 11. Reference Samples

Deterministic reference samples live under `samples/`:

- `samples/bilanz-output-happy-path.md` + `.json` — all seven wellen
  complete, drift and latency clean, Phase-3-COMPLETE marker valid.
- `samples/bilanz-output-rollback-path.md` + `.json` — Marathon
  rollback at welle-4: partial counts, welle-7 sign-off absent,
  COMPLETE marker missing.

Both samples are produced from the inline mock datasets in
`tests/observability/test_bilanz_generator_validation_runs.py`
(see the `_marathon_state_*`, `_drift_histograms_*`, `_sign_offs_*`,
`_complete_marker_*` helpers); re-run the generator against those
fixtures to regenerate.

## 12. Anchors

- ADR-0065 (Phase-3c Cutover Plan, approved 2026-05-17 ~18:10 CEST).
- ADR-0066 (Phase-3c 4W-Beschleunigung).
- PR #280 — Phase-3 Final Bilanz Generator (Tag-43, Noa).
- Tag-44 — Bilanz Validation Mock Runs + Output-Schema Validation (this PR).

-- Noa
