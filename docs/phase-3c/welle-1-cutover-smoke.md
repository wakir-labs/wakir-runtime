# Phase-3c Welle-1 Cutover-Smoke Runbook (`v907_verify`)

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), Tomás Reinhart (Matrix-Lead) |
| ADR | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md) |
| Script (Python) | [`scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py`](../../scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py) |
| Script (Bash wrapper) | [`scripts/phase-3c/welle-1-v907-verify-cutover-smoke.sh`](../../scripts/phase-3c/welle-1-v907-verify-cutover-smoke.sh) |
| Tests | [`tests/phase_3c/test_welle_1_cutover_smoke.py`](../../tests/phase_3c/test_welle_1_cutover_smoke.py) |
| Sibling | [`docs/operations/phase-3c-welle-1-runbook.md`](../operations/phase-3c-welle-1-runbook.md) (CI Validation-Workflow); [`scripts/phase-3c-cutover-dry-run.py`](../../scripts/phase-3c-cutover-dry-run.py) (feasibility probe) |

## Purpose

This runbook describes the **End-to-End Cutover-Smoke** for ADR-0065
Welle-1 (`v907_verify`, KW 22 → KW 24-25). The smoke is the
strict, asserts-tragend counterpart to the feasibility-probe dry-run
that operators run before the Pilot-VM Quadlet default of
`WAKIR_V907_VERIFY_BACKEND` is flipped from `python` to `rust`.

The smoke is **not** the Monday Live-Smoke (that one is Pilot-VM
operator-hand-territory). It is the local-hermetic precursor: it
exercises the full pre-cutover / cutover-step / post-cutover /
rollback shape against a mocked persona-engine and emits a tri-state
exit code the operator can wire into shell gates and PR checks.

## Operator usage

```bash
# Default GREEN-path run (8 boots per phase, all asserts strict).
python3 scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py \
    --output out/welle-1-smoke.json
echo "exit=$?"

# Same via the bash wrapper.
bash scripts/phase-3c/welle-1-v907-verify-cutover-smoke.sh \
    --output out/welle-1-smoke.json

# Tighter latency tolerance (10 % instead of ADR-0065 §AC-2 20 %).
python3 scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py \
    --latency-tolerance-pct 10

# ADR-0065 §Option-B-prose 7-component interpretation (vs. engine
# inventory 8).
python3 scripts/phase-3c/welle-1-v907-verify-cutover-smoke.py \
    --expected-components 7
```

## Decision matrix

The smoke evaluates six checks per run. Each check is tagged as
**blocker** (failure → exit 2 ROLLBACK_RECOMMENDED) or **caution**
(failure → exit 1 CAUTION; mixed blocker+caution → exit 2).

| ID | Check | Severity | What it verifies |
|---|---|---|---|
| A1 | backend-flip | blocker | Every focus-component BackendDecision on the post-cutover phase reports `chosen_backend == "rust"`. |
| A2 | cross-lang parity-hash | blocker | SHA-256 over `(domain, fallback_reason)` for focus-component records is identical between **Post-Cutover-Rust** and **Rollback-Python** (the two clean happy-paths). `requested_backend` and `chosen_backend` are both projected out (env-var flip naturally changes the former; resolver flip changes the latter). The Pre-Cutover phase is *not* in the parity comparison: it is the explicit-python branch by resolver design, with `fallback_reason="explicit_python"`, which is semantically distinct from the implicit-python branch — that distinction is what R1 verifies. Mirrors the substrate-level invariant PR #224 SVID Cross-Lang Pins and PR #170 Anchor-Emitter Cross-Lang fixtures pinned at the Bridge-Audit-Writer layer. |
| A3 | latency within tolerance | caution | P95 focus-component latency on the post-cutover (Rust) path is at most `pre_p95 + tolerance_pct %`. Tolerance defaults to 20 % per ADR-0065 §AC-2. |
| A4 | decision-count in-place | caution | Engine emits exactly `expected_components` BackendDecisions per boot on the post-cutover phase. Default `expected_components` tracks the engine inventory (8 — `v907_verify, svid_workload_identity, bridge_diff, anchor_emitter, state_backing, fsm, subscribe_loop, recovery`). Operators invoking the ADR-0065-prose interpretation pass `--expected-components 7`. |
| A5 | fallback-clean | blocker | Zero BackendDecision records on the focus component post-cutover phase carry a non-null `fallback_reason`. A fallback would mean the engine silently dropped back to Python and the audit-record would not say `backend: rust`. |
| R1 | rollback to Python | blocker | After unsetting `WAKIR_V907_VERIFY_BACKEND`, every focus-component BackendDecision reports `chosen_backend == "python"` again. Verifies the ≤10 min rollback path per ADR-0065 §Rollback-SLA. |

## Exit-code interpretation

| Exit | Band | Operator action |
|---|---|---|
| 0 | GREEN | Welle-1 cutover-PR can proceed to the Monday Pilot-VM Live-Smoke per ADR-0065 §Verifikations-Plan. The JSON envelope is admissible as cutover-PR evidence. |
| 1 | CAUTION | At least one caution-severity check failed (A3 latency drift, A4 component-count drift). The engine substance is intact (backend-flip + parity + rollback all OK). **Investigate before the Monday Live-Smoke**: latency drift may indicate Rust-binary build-flag drift; component-count drift may indicate engine-inventory drift since the ADR-0065 baseline. Escalate to Tomás (Matrix-Lead) for go/no-go. |
| 2 | ROLLBACK_RECOMMENDED | At least one blocker-severity check failed (A1, A2, A5, or R1). Do not proceed to the Monday Live-Smoke. Open a substance-bug-issue (label `welle-1-smoke-fail`), eskaliert to Priya (CTO) per ADR-0065 §Rollback-Procedure Step 1. |
| 3+ | (not used by smoke) | I/O failure (`--output` not writable) is reported as exit 2 by convention — operator must consume the evidence before proceeding. |

## Envelope shape

The smoke emits a JSON envelope to `--output` (or stdout). The
top-level keys are:

```text
schema                    "wakir.phase-3c.welle-1-cutover-smoke/1"
timestamp_utc             POSIX-epoch integer
welle                     1
focus_component           "v907_verify"
focus_env_var             "WAKIR_V907_VERIFY_BACKEND"
engine_boot_components    list of in-place component names (default 8)
expected_components       int (CLI arg)
boots_per_phase           int (CLI arg)
latency_tolerance_pct     int (CLI arg)
phases                    { "pre_cutover_python_baseline": {...},
                            "post_cutover_rust":          {...},
                            "rollback_python":            {...} }
asserts                   { A1, A2, A3, A4, A5, R1 → {passed, severity, detail} }
exit_code                 0 | 1 | 2
band                      "GREEN" | "CAUTION" | "ROLLBACK_RECOMMENDED"
```

Each `phases[*]` sub-record carries `boots`, `decision_count`,
`focus_p95_latency_us`, `parity_hash` (raw, including
`chosen_backend`), and `focus_parity_hash_normalised` (the A2-relevant
projection, with `chosen_backend` stripped).

## Hermeticity contract

The smoke is **stdlib-only**. It never:

* Invokes the real Rust binary (`_binary_available` is stubbed to
  always-true; the smoke focuses on the backend-switch behaviour, not
  the binary-deployment posture — that's a separate Quadlet-Installer
  prerequisite per ADR-0065 §Trigger-Bedingung-3).
* Talks to NATS, the Anthropic API, or any container runtime.
* Mutates `os.environ` (the engine sees a private mapping).
* Reads `tests/fixtures/*` from disk; the parity-hash is computed
  in-memory over the mocked engine's decision-records. The
  fixture-pointer to PR #170 (Anchor-Emitter Cross-Lang) and PR #224
  (SVID Cross-Lang Pins) is *documentary* — those fixtures are the
  substrate-level oracle; this smoke is the engine-emission-level
  shadow.

## Welle-2..7 forward-compat

The script's focus-component / focus-env-var / engine-boot-components
constants are top-level module symbols. Future Welle-N cutover-smokes
can be written by copying this file and re-pointing those constants.
The asserts-evaluation logic is component-agnostic except for the A2
parity-hash projection, which uses the focus-component name verbatim.

## Cross-references

* **ADR-0065** §Verifikations-Plan (decision matrix derives from
  §AC-1..§AC-5 and §Rollback-Procedure).
* **ADR-0066** Mini-Welle solo-track that runs in parallel to ADR-0065
  during the 7-Wochen-Marathon.
* **PR #170** Anchor-Emitter Cross-Lang fixtures (Tag-23) — A2
  parity-hash references this as substrate-level oracle.
* **PR #179** BackendDecision Observability (Tag-24) — A3 latency
  tolerance derives from the same percentile machinery this script
  reuses (`_nearest_rank_percentile`).
* **PR #224** SVID Cross-Lang Pins (Tag-33) — closes the engine-side
  byte-equal-output contract for `svid_workload_identity`; this
  smoke replicates the same contract pattern locally for
  `v907_verify`.
* **`docs/operations/phase-3c-welle-1-runbook.md`** — the upstream
  Welle-1 Validation CI workflow runbook. The CI workflow's Step 2
  consumes `phase-3c-cutover-dry-run.py`; this Cutover-Smoke is the
  stricter sibling for operator-hand evidence.

---

_— Selin Çelik (Persona-Engine), Tag-34, 2026-05-18._
