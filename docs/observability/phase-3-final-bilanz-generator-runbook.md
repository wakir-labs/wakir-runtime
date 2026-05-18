# Phase-3 Final Bilanz Generator -- Runbook

Owner: Noa Bergstrom (SRE).
Status: Tag-43 substanz.
Related code: `scripts/observability/phase-3-final-bilanz-generator.py`.
Related tests: `tests/observability/test_phase_3_final_bilanz_generator.py`.

---

## 1. Purpose

The Phase-3 Marathon (KW-21..KW-27, ~2026-05-12..~2026-06-29) drives
seven cutover-Wellen from Python-default to Rust-default. The end of
the Marathon needs **one consolidated artefact** that:

  1. Pulls every observability stream into a single Markdown
     bilanz operator-readable end-to-end.
  2. Emits a machine-readable JSON rollup for Henrik (Internal
     Audit) and the Phase-4 pre-substanz aufstellung.
  3. Validates the Phase-3-COMPLETE-marker (presence + status +
     welle-count + approver + completed_at).
  4. Surfaces follow-up items derived from the bilanz itself, not
     hand-edited.

This runbook describes when and how to invoke the generator and what
to do when it reports a breach.

## 2. When to run

### 2.1 Manual

Run the generator any time during the Marathon to get a current
bilanz snapshot. Two typical scenarios:

  * **Mid-Marathon checkpoint** -- after each Welle Henrik sign-off,
    run the generator to confirm the cumulative state. The bilanz
    will mark not-yet-completed wellen as `NO_DATA` rather than
    failing.
  * **End-of-Marathon final** -- run the generator after the
    Phase-3-COMPLETE-marker has been written. This produces the
    artefact handed to the Aufsichtsrat and to Henrik.

```
python3 scripts/observability/phase-3-final-bilanz-generator.py
```

All paths default to the canonical `state/` and `reports/`
directories. Override with the flags described in section 4.

### 2.2 Auto-trigger (workflow hook)

The workflow hook that watches the COMPLETE-marker invokes the
generator with `--auto-after-complete-marker`. In that mode:

  * If the marker file is missing -> exit 0 silently.
  * If the marker file exists but `status != "COMPLETE"` -> exit 0
    silently.
  * If the marker is COMPLETE -> generate the bilanz and exit 0.

This makes the hook idempotent and safe to fire on every state-file
change.

```
python3 scripts/observability/phase-3-final-bilanz-generator.py \
    --auto-after-complete-marker
```

### 2.3 Strict mode (CI gating)

The `--strict` flag turns the bilanz into a CI gate: it exits 1 if
any of:

  * latency BREACH on >=1 welle, or
  * drift BREACH on >=1 welle, or
  * audit aggregate not OK (missing sign-off, audit_ok=false, or
    exception_count > 0 anywhere), or
  * COMPLETE-marker not valid.

Use strict mode in the Phase-4 readiness CI job. Do not use it in
the auto-trigger hook (the hook is informational, not gating).

## 3. Inputs

The generator reads six observability streams. Each path is overridable.

| Stream | Default path | Owner | Schema |
|---|---|---|---|
| Marathon-Aggregat-Tracker state | `state/phase-3-marathon-state.json` | Selin #261 | per-welle cutover counts + latency samples |
| ci-aggregator failure-rate history | `state/aggregator-failure-rate-history.json` | Noa #251 | list of aggregator runs |
| BackendDecision snapshots (per welle) | `state/backend-decision-snapshots/<welle-id>.json` | Noa Tag-41 | list of snapshot dicts per welle |
| Cross-welle drift histograms | `state/cross-welle-drift-histograms.json` | Noa Tag-41 | per-welle drift-pct samples |
| Henrik per-welle sign-off | `state/welle-N-sign-off.json` (glob) | Henrik | sign-off dict |
| Phase-3-COMPLETE marker | `state/phase-3-complete-marker.json` | Tomas #258 | marker dict |

If a stream is missing the generator falls back to "no data" -- it
does not abort. The exception is the Marathon-Aggregat-Tracker state
file: without it the generator cannot produce a useful bilanz and
exits 2.

### 3.1 Schema snippets

```json
// state/phase-3-marathon-state.json
{
  "schema_version": "1.0.0",
  "updated_at": "2026-06-29T11:00:00Z",
  "wellen": {
    "welle-1-v907-verify": {
      "cutover_runs_total": 4123,
      "cutover_runs_rust": 3987,
      "cutover_runs_python_fallback": 136,
      "decision_latency_ms_samples": [120, 230, 312, 421],
      "last_sample_at": "2026-06-29T10:45:00Z"
    },
    ...
  }
}
```

```json
// state/welle-N-sign-off.json (one per welle)
{
  "welle_id": "welle-3-bridge-audit-writer",
  "signed_off_at": "2026-06-05T15:30:00Z",
  "signed_off_by": "henrik",
  "audit_findings": ["minor: ..."],
  "exception_count": 0,
  "audit_ok": true
}
```

```json
// state/phase-3-complete-marker.json
{
  "schema_version": "1.0.0",
  "status": "COMPLETE",
  "completed_at": "2026-06-29T23:59:00Z",
  "wellen_complete": 7,
  "approver": "tomas",
  "evidence_refs": ["state/welle-1-sign-off.json", "..."]
}
```

## 4. CLI surface

```
phase-3-final-bilanz-generator.py
    [--marathon-state PATH]
    [--aggregator-history PATH]
    [--backend-snapshots-dir DIR]
    [--drift-histograms PATH]
    [--sign-off-glob GLOB]
    [--complete-marker PATH]
    [--output-md PATH]
    [--output-json PATH]
    [--now-iso ISO_TIMESTAMP]    # test-only override
    [--auto-after-complete-marker]
    [--strict]
```

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Bilanz written (or auto-trigger no-op). |
| 1 | Strict mode: breach detected. |
| 2 | Required input missing or unreadable. |

## 5. Outputs

Two files written atomically:

  * `reports/phase-3-marathon-bilanz.md` -- ~500..800 lines Markdown.
  * `reports/phase-3-marathon-bilanz.json` -- machine-readable rollup.

Both are deterministic for fixed input + fixed `--now-iso`.

### 5.1 Markdown structure

  1. Header / metadata (generated_at, schema_version).
  2. Executive summary (welle counts, drift counts, latency counts,
     marker valid, audit aggregate).
  3. Per-welle mini-bilanz (sections 2.1..2.7, one per welle:
     substanz-anker, latency, snapshots, drift, sign-off).
  4. Cross-welle coupling (wait-loop latency, sub-workflow buckets).
  5. Henrik audit aggregate (sign-off table).
  6. Phase-3-COMPLETE-marker validation.
  7. Phase-4 follow-up items (derived).
  8. Source-of-truth inputs.

### 5.2 JSON structure

The JSON is a single object with keys:

  * `schema_version`
  * `generated_at`
  * `executive_summary`
  * `per_welle` (keyed by welle-id)
  * `aggregator_history_rollup`
  * `complete_marker_validation`
  * `audit_aggregate`
  * `phase_4_followups`

## 6. SLO budgets

The generator references two ADR-0065 budgets:

  * **Per-welle p95 decision latency** (`LATENCY_BUDGET_MS` constant).
    WARN at `p95 > 0.9 * budget`, BREACH at `p95 > 1.1 * budget`.
  * **Cross-welle drift budget** = 0.5 % (`DRIFT_BUDGET_PCT`).
    WARN at `> 0.4 %`, BREACH at `> 0.5 %`.

If the ADR changes the budgets, update the constants at the top of
the script and re-run the test suite. Do not hard-edit the budgets
in the bilanz output.

## 7. Failure modes and remediation

| Symptom | Likely cause | Remediation |
|---|---|---|
| Generator exits 2 with "marathon-state file missing" | Selin's tracker not yet written | Verify Tag-40 Marathon-Aggregat-Tracker is running; check `state/` permissions |
| Bilanz shows `NO_DATA` for all latency p95 | Decision-latency-samples not collected | Confirm Selin's tracker is sampling; check `decision_latency_ms_samples` is populated |
| Drift BREACH on multiple wellen at once | Systemic NATS/SPIFFE issue, not welle-local | Page Kai (Container-Infra) before continuing the Marathon |
| Missing Henrik sign-off | Henrik audit not yet filed | Block Phase-4 start until sign-off is filed |
| COMPLETE-marker valid but audit aggregate not OK | Sign-off filed with `audit_ok=false` | Re-open the welle; do not proceed to Phase-4 |
| Strict mode exits 1 in CI | A BREACH was detected | Open the bilanz Markdown; resolve each BREACH; re-run |

## 8. Operator workflow

Recommended end-of-Marathon sequence:

  1. Confirm all seven `state/welle-N-sign-off.json` files are
     present (Henrik check).
  2. Tomas writes `state/phase-3-complete-marker.json` with status
     COMPLETE (Tag-42 PR #258 spec).
  3. The auto-trigger hook fires the generator.
  4. Mira reviews `reports/phase-3-marathon-bilanz.md`.
  5. If the bilanz has zero BREACH and zero follow-ups: Phase-4
     pre-substanz aufstellung may start.
  6. If breaches or follow-ups exist: Mira routes them as
     Phase-4 work-items before Phase-4 kick-off.

## 9. Hermetic test surface

Tests live in `tests/observability/test_phase_3_final_bilanz_generator.py`.
The suite covers:

  * percentile helper edge cases (n=0, n=1, n>=2)
  * latency_status / drift_status thresholds
  * marathon-state normalization (full + missing-welle cases)
  * aggregator-history rollup (full + empty)
  * backend-snapshot rollup
  * drift histogram BREACH surfacing
  * sign-off aggregation (full + missing)
  * COMPLETE-marker validation (valid, missing, partial, wrong-status)
  * assemble_bilanz happy-path
  * assemble_bilanz with breaches surfacing follow-ups
  * Markdown render structural checks
  * main() end-to-end with disk fixtures
  * --auto-after-complete-marker short-circuit (missing + not-complete)
  * --strict exits non-zero on BREACH
  * determinism of assemble_bilanz
  * --marathon-state missing -> rc 2 with stderr

Run locally:

```
python3 -m pytest tests/observability/test_phase_3_final_bilanz_generator.py -v
```

29 tests, target wall-clock < 1 s.

## 10. Cross-review zones

  * **Zone H (Noa x Kai):** Kai owns the workflow runner that
    invokes the auto-trigger hook. Coordinate before changing
    the script's CLI surface.
  * **Zone I (Noa x Tomas):** Tomas owns the COMPLETE-marker
    schema. Coordinate before changing
    `validate_complete_marker()` keys.
  * **Henrik (Internal Audit):** consumes the JSON output. Notify
    if `phase_4_followups` semantics change.

## 11. Changelog

  * 2026-05-18 -- v1.0.0 -- Tag-43 substanz, Noa.

-- Noa
