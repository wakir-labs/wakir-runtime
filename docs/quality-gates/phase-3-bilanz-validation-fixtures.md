# Phase-3 Bilanz Validation Fixtures

**Quality-gate document, Tag-44 (Selin Çelik, Persona-Engine).**

This document is the operator reference for the five canonical
fixture datasets used to validate Noa's Phase-3 Final Bilanz
Generator (Tag-43 PR #280,
`scripts/observability/phase-3-final-bilanz-generator.py`).

## Why this gate exists

The Phase-3 Marathon (KW-21..KW-27) drives seven cutover-Wellen from
Python-default to Rust-default. At the end of the Marathon Tomas
writes the Phase-3-COMPLETE-marker; that write triggers the
`phase-3-final-bilanz-generator` workflow, which stitches seven
observability streams into a single end-of-Marathon bilanz that
Henrik (Internal Audit) consumes and Phase-4 inherits.

If the bilanz generator misreads any of those streams the
Phase-3-COMPLETE acceptance becomes opaque. Two failure modes are
particularly dangerous:

1. **False-green:** the generator reports `is_complete=true` when
   one or more wellen actually drifted or rolled back. Phase-4 starts
   on a corrupt baseline.
2. **False-red:** the generator reports `is_complete=false` when the
   marathon legitimately finished. Operator hand has to override; the
   override path is not audited.

Both failure modes are observability bugs, not substance bugs. The
existing Noa test suite
(`tests/observability/test_phase_3_final_bilanz_generator.py`)
exercises the generator with synthetic dicts but does not pin the
generator against on-disk fixtures that represent realistic Marathon
end-states. This gate fills that gap.

## What the fixtures cover

The five datasets under
`tests/fixtures/phase-3-marathon-bilanz/<name>/state/` represent the
end-states the operator most needs to be confident the generator
handles correctly. Each dataset is a self-contained `state/` tree;
the generator can be pointed at it directly via its CLI flags.

| Dataset | What it represents | Expected bilanz verdict |
|---|---|---|
| `happy-path/` | Clean 7-welle Marathon. All `audit_ok=true`, marker `COMPLETE`, no drift, no latency excursion. | `complete_marker_is_complete=true`, `audit_aggregate_ok=true`, zero follow-ups (canonical no-follow-ups sentinel). |
| `rollback-path/` | Welle-3 rolled back; W4..W7 never started; no COMPLETE marker. W3 sign-off carries `audit_ok=false` with three audit findings. | `is_complete=false` (marker absent), 4 missing sign-offs, audit aggregate not OK, follow-ups call out rollback. |
| `welle-7-missing/` | W1..W6 signed off, W7 pre-auditor decision absent. Marker exists with `wellen_complete=6` (premature). | Marker validation error `wellen_complete_expected_7`, audit aggregate not OK, W7 listed as missing sign-off. |
| `cross-drift/` | W4 and W5 simultaneously above the 0.5 % drift budget (systemic-coupling signal: NATS/SPIFFE/wirelang scope). | 2 drift BREACHes, follow-ups name both W4 and W5, audit aggregate downgraded. |
| `latency-excursion/` | All audits green but W3 and W5 p95 decision latency above budget (1.1x). | Audit aggregate OK, complete marker valid, 2 latency BREACHes surfaced via follow-ups only. |

These five datasets are deliberately chosen to **cover the four
status combinations** the operator most cares about:

* `audit_OK & marker_valid` happy-path: must not show false-red.
* `audit_NOT_OK & marker_invalid` rollback: must not show false-green.
* `audit_NOT_OK & marker_invalid` premature-completion: must surface
  the marker error explicitly.
* `audit_OK & marker_valid & latency_BREACH`: must surface latency
  follow-ups without polluting the audit aggregate.
* `audit_NOT_OK & marker_valid & cross-welle drift`: must reveal
  cross-welle coupling rather than treating each welle in isolation.

## Source-of-truth: regenerator builders

The on-disk fixtures are not hand-edited. They are produced by:

```
python3 tests/fixtures/phase-3-marathon-bilanz/regenerate.py
```

The builder file
(`tests/fixtures/phase-3-marathon-bilanz/regenerate.py`) holds
deterministic builders for each dataset; manual edits will lose to
the next regenerate-and-commit cycle.

**Byte-stability guarantee:** every JSON is written with
`sort_keys=True`, `indent=2`, trailing `\n`, UTF-8 no-BOM. The test
`test_fixtures_are_byte_stable` compares on-disk SHA-256 against a
fresh regeneration; any drift fails CI with a clear "run
regenerate.py" hint.

## Generator-constant pinning

The regenerator file imports neither the generator script nor any
third-party library. It re-declares `WELLE_ORDER` and
`LATENCY_BUDGET_MS` so the regenerator stays stdlib-only (matching
the generator's sandbox boundary).

To prevent silent drift between the two declarations, two consistency
tests assert exact equality:

* `test_welle_order_matches_generator`
* `test_latency_budget_matches_generator`

If Noa adds an eighth welle or rebalances a budget, both files must
update together; CI will fail until they do.

## Test layout

`tests/fixtures/phase-3-marathon-bilanz/test_bilanz_generator_with_fixtures.py`
contains six categories of test:

1. **Schema-validity sweep** (5 datasets x 5 file types = 25 cases):
   every JSON parses, every required top-level key is present.
2. **Byte-stability sweep** (5 cases): regenerator output matches
   on-disk SHA-256.
3. **Generator-constant consistency** (2 cases): WELLE_ORDER and
   LATENCY_BUDGET_MS match between generator and regenerator.
4. **Per-dataset verdict assertions** (5 cases): each dataset is fed
   to `assemble_bilanz` and the resulting executive_summary +
   follow-ups must match the documented expectations.
5. **Strict-mode breach detection** (5 cases, parameterised): `happy-path`
   produces zero breaches; the four problem-state datasets each
   produce at least one.
6. **Markdown rendering smoke** (5 cases): `render_markdown` produces
   the 7-section output structure with every active welle's short
   label.

Total: **47 hermetic test cases**, all stdlib-only, runtime well
under 1 second on a CI runner.

## CI integration

The `phase-3-final-bilanz-generator` workflow runs the fixture
validation test suite on:

* `push` to `main` touching the generator, generator tests, or any
  file under `tests/fixtures/phase-3-marathon-bilanz/`;
* every `pull_request` touching the same paths;
* `workflow_dispatch` (operator-manual).

The generate step uses `--auto-after-complete-marker`, so it remains
idempotent on PRs (exits 0 if the COMPLETE-marker is absent or not
COMPLETE). PRs therefore only exercise the test job, not the
artefact-generation step.

## Operator workflow: adding a new fixture dataset

1. Add a builder function to `regenerate.py` (`build_<name>()`).
2. Register it in the `DATASETS` dict.
3. Run `python3 tests/fixtures/phase-3-marathon-bilanz/regenerate.py`.
4. Add a verdict-assertion test in `test_bilanz_generator_with_fixtures.py`.
5. Update the dataset table at the top of this document.
6. Update the README.md in the fixtures root.
7. Commit all files in a single change-set.

## Operator workflow: updating the generator

If Noa changes the generator's input or output schema:

1. Update `regenerate.py` builders to produce the new shape.
2. Run `regenerate.py` to refresh the on-disk fixtures.
3. Update the verdict-assertion tests if any expected verdict
   changed.
4. Run the full fixture test suite; all 47 cases must pass.
5. Commit the generator change + fixture refresh + test refresh as
   one PR.

## Anchors

* Tag-43 PR #280 (Noa) -- Bilanz-Generator + initial test suite.
* Tag-43 PR #281 (Noa) -- Cutover-Operator-Cheat-Sheet.
* Tag-42 PR #258 (Tomas) -- Phase-3-COMPLETE-marker spec.
* Tag-40 PR #261 (Selin) -- Marathon-Aggregat-Tracker.
* Tag-38 PR #251 (Noa) -- CI-Aggregator-Failure-Rate-Tracker.
* ADR-0065 -- Phase-3c Cutover Plan.
* ADR-0066 -- Phase-3c 4W-Beschleunigung.
* ADR-0068 -- ci-aggregator single Required-Status-Check.

-- Selin
