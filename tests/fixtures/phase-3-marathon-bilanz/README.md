# Phase-3-Marathon-Bilanz Sample Datasets

Five hermetic fixture datasets that validate Noa's Phase-3 Final
Bilanz Generator (`scripts/observability/phase-3-final-bilanz-generator.py`,
introduced in Tag-43 PR #280).

Each dataset is a self-contained `state/` tree following the input
shape declared by the generator's CLI defaults:

```
state/
  phase-3-marathon-state.json
  aggregator-failure-rate-history.json
  cross-welle-drift-histograms.json
  phase-3-complete-marker.json
  welle-1-sign-off.json .. welle-7-sign-off.json
  backend-decision-snapshots/
    welle-1-v907-verify.json
    ...
    welle-7-recovery-workflow.json
```

## Datasets

| Dataset | Purpose | Expected verdict |
|---|---|---|
| `happy-path/` | All 7 wellen GREEN, all sign-offs in, marker COMPLETE | bilanz `audit_aggregate_ok = true`, `complete_marker_is_complete = true`, 0 follow-ups |
| `rollback-path/` | Welle-3 rolled back, W4..W7 blocked, marker absent | marker `is_complete = false`, missing sign-offs 3..7 |
| `welle-7-missing/` | W1..W6 signed off, W7-Pre-Auditor-Decision absent | aggregate audit not OK, missing sign-off W7 |
| `cross-drift/` | W4 + W5 both above drift budget simultaneously | 2 wellen drift BREACH (systemic-coupling signal) |
| `latency-excursion/` | All verdicts GREEN, latency p95 above budget for W3 + W5 | latency status BREACH on W3 and W5, audit still aggregate-OK |

## Byte-stability guarantee

All JSON files are written with:

* `sort_keys=True`
* `indent=2`
* trailing `\n`
* UTF-8, no BOM

This is enforced by the regenerator script
(`tests/fixtures/phase-3-marathon-bilanz/regenerate.py`) and verified
by the byte-stability test in
`test_bilanz_generator_with_fixtures.py::test_fixtures_are_byte_stable`.

## Schema versions

* Marathon-Tracker: `1.0.0` (Selin #261)
* CI-Aggregator-History: Noa #251 format (list of entries, no
  top-level wrapper)
* Backend-Decision-Snapshots: per-welle list (Reza/Selin agreed shape)
* Cross-Welle-Drift-Histograms: Noa Tag-41 format
* Sign-Off: Henrik per-welle shape (audit_ok, exception_count, ...)
* COMPLETE-Marker: `1.0.0` (Tomas #258)

## Regenerating fixtures

Manual edits will break byte-stability. Always regenerate via:

```
python3 tests/fixtures/phase-3-marathon-bilanz/regenerate.py
```

This is invoked from `test_bilanz_generator_with_fixtures.py` to
verify the on-disk fixtures match the source-of-truth Python builder.

-- Selin
