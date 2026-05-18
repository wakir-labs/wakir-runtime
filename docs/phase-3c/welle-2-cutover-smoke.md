# Phase-3c Welle-2 Cutover-Smoke Runbook (`svid_workload_identity`)

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), Tomás Reinhart (Matrix-Lead) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md), [0066](../../decisions/0066-phase-3c-doppel-cutover-acceleration-kw24.md) |
| Script (Python) | [`scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py`](../../scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py) |
| Script (Bash wrapper) | [`scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.sh`](../../scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.sh) |
| Tests | [`tests/phase_3c/test_welle_2_cutover_smoke.py`](../../tests/phase_3c/test_welle_2_cutover_smoke.py) |
| Sibling | [`docs/phase-3c/welle-1-cutover-smoke.md`](welle-1-cutover-smoke.md) (parallel KW-24 doppel-cutover); [`scripts/phase-3c-cutover-dry-run.py`](../../scripts/phase-3c-cutover-dry-run.py) (feasibility probe) |

## Purpose

This runbook describes the **End-to-End Cutover-Smoke** for ADR-0065
Welle-2 (`svid_workload_identity`) inside the ADR-0066 **KW-24
doppel-cutover**: Welle-1 (`v907_verify`) and Welle-2
(`svid_workload_identity`) flip on the Pilot-VM in the same
operator-hand window.

The smoke is **not** the Monday Live-Smoke (that one is Pilot-VM
operator-hand-territory). It is the local-hermetic precursor: it
exercises the full pre-cutover / cutover-step / post-cutover /
rollback shape against the real
`resolve_svid_workload_identity_backend` resolver from PR #191
(`7e2defb`) and emits a tri-state exit code the operator can wire
into shell gates and PR checks. The pattern mirrors the Welle-1
sibling byte-for-byte; the operator runs both back-to-back during
the KW-24 doppel-cutover window and reads two JSON envelopes.

## Substrate inventory

| Substrate | PR | Commit | Role |
|---|---|---|---|
| Rust-Default-Backend-Resolver | [#191](https://github.com/wakir-labs/wakir-runtime/pull/191) | `7e2defb` | The real `resolve_svid_workload_identity_backend` the smoke verifies end-to-end. |
| Container-Image-Build-Pipeline | [#201](https://github.com/wakir-labs/wakir-runtime/pull/201) | `cddce13` | Single-binary Rust-CLI image for the Welle-2 Quadlet. |
| Welle-2-Validation-Workflow | [#196](https://github.com/wakir-labs/wakir-runtime/pull/196) | `2a33a8c` | CI Validation lane that consumes the dry-run + this smoke. |
| SVID Cross-Lang Pins | [#224](https://github.com/wakir-labs/wakir-runtime/pull/224) | `de47cb3` | The five fixture vectors (`tests/fixtures/svid-workload-cross-lang/fixtures.json`) that A6 cross-checks. |
| federation_resolver wire-in | [#200](https://github.com/wakir-labs/wakir-runtime/pull/200) | `1ea7a60` | Added the 9th BackendDecision; default `--expected-components 9` tracks this. |

## Operator usage

```bash
# Default GREEN-path run (8 boots per phase, all asserts strict,
# 9 expected components after PR #200 federation_resolver).
python3 scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py \
    --output out/welle-2-smoke.json
echo "exit=$?"

# Same via the bash wrapper.
bash scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.sh \
    --output out/welle-2-smoke.json

# Tighter latency tolerance (10 % instead of ADR-0065 §AC-2 20 %).
python3 scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py \
    --latency-tolerance-pct 10

# ADR-0065 §Option-B-prose 7-component interpretation (vs. current
# engine inventory 9 after PR #200 federation_resolver).
python3 scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py \
    --expected-components 7

# Skip the A6 SVID Cross-Lang substrate-parity probe when the wirelang
# package is not importable in the run environment (CI lanes with a
# minimal subset).
python3 scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py \
    --skip-svid-fixture-parity
```

## KW-24 doppel-cutover sequencing

Per ADR-0066, the operator runs Welle-1 and Welle-2 smokes in the
**same** Monday operator-hand window. The recommended sequence:

1. Run **Welle-1** smoke → expect `band=GREEN`, exit 0.
2. Run **Welle-2** smoke → expect `band=GREEN`, exit 0.
3. Verify both JSON envelopes attach cleanly to the doppel-cutover PR.
4. Proceed to the Pilot-VM Live-Smoke per ADR-0065 §Verifikations-Plan
   Mo.

If **either** smoke reports `band=CAUTION` or `band=ROLLBACK_RECOMMENDED`,
the operator pauses the **entire** doppel-cutover (both waves) per
ADR-0066 §KW-24-Rollback-Coupling — partial cutover (only one of the
two waves succeeds) is explicitly forbidden by ADR-0066.

## Decision matrix

The smoke evaluates seven checks per run. Each check is tagged as
**blocker** (failure → exit 2 ROLLBACK_RECOMMENDED) or **caution**
(failure → exit 1 CAUTION; mixed blocker+caution → exit 2).

| ID | Check | Severity | What it verifies |
|---|---|---|---|
| A1 | backend-flip | blocker | Every focus-component (`svid_workload_identity`) BackendDecision on the post-cutover phase reports `chosen_backend == "rust"`. |
| A2 | cross-lang parity-hash | blocker | SHA-256 over `(domain, fallback_reason)` for focus-component records is identical between **Post-Cutover-Rust** and **Rollback-Python** (the two clean happy-paths). `requested_backend` and `chosen_backend` are both projected out (env-var flip naturally changes the former; resolver flip changes the latter). The Pre-Cutover phase is *not* in the parity comparison: it is the explicit-python branch by resolver design (`fallback_reason="explicit_python"`), semantically distinct from the implicit-python branch — that distinction is what R1 verifies. Mirrors the substrate-level invariant PR #224 SVID Cross-Lang Pins and PR #170 Anchor-Emitter Cross-Lang fixtures pinned at the Bridge-Audit-Writer layer. |
| A3 | latency within tolerance | caution | P95 focus-component latency on the post-cutover (Rust) path is at most `pre_p95 + tolerance_pct %`. Tolerance defaults to 20 % per ADR-0065 §AC-2. |
| A4 | decision-count in-place | caution | Engine emits exactly `expected_components` BackendDecisions per boot on the post-cutover phase. Default `expected_components` tracks the engine inventory (9 after PR #200 federation_resolver wire-in — `v907_verify, svid_workload_identity, bridge_diff, anchor_emitter, state_backing, fsm, subscribe_loop, recovery, federation_resolver`). Operators invoking the ADR-0065-prose interpretation pass `--expected-components 7`. |
| A5 | fallback-clean | blocker | Zero BackendDecision records on the focus component post-cutover phase carry a non-null `fallback_reason`. A fallback would mean the engine silently dropped back to Python and the audit-record would not say `backend: rust`. **Live-substrate caveat:** until the `persona-engine-svid-workload-identity` Rust crate ships a real `FetchX509SVID` runtime, the live operator-VM resolver's `fallback_reason="binary_missing"` is the **expected** signal per the PR #191 Tag-25 wire-in docstring; the smoke's stub-probe path keeps A5 demonstrably-green, but live Pilot-VM runs against the un-shipped crate will see A5 fail. That is the ADR-0065 Welle-2 *precondition* signal, not a smoke bug — operators read it as "Welle-2 image not yet deployed". |
| R1 | rollback to Python | blocker | After unsetting `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND`, every focus-component BackendDecision reports `chosen_backend == "python"` again. Verifies the ≤10 min rollback path per ADR-0065 §Rollback-SLA. |
| A6 | SVID Cross-Lang fixture-parity | caution | Recompute the SHA-256 snapshot hash of each PR #224 fixture vector via the **Python authority** (`wirelang.identity.svid_workload_identity_canonical.build_snapshot_from_bindings` + `snapshot_sha256_hex` + `build_binding`) and assert byte-equality with the pinned baselines. Five fixtures: `f01-empty-identity-set`, `f02-single-org-single-spiffe`, `f03-multi-org-cross-mapping`, `f04-key-rotation-svid-replay`, `f05-expired-svid-rejection`. *Caution-severity*: drift here means the canonical encoder shifted since the Tag-33 pin (a Tomás-Zone-K substrate-review signal), but the engine-emission-level cutover (A1..A5) is independent. Skipped + reported as `passed=true, skipped=true` when the canonical module or fixture file are missing (test-CI lanes without the wirelang package). |

## Exit-code interpretation

| Exit | Band | Operator action |
|---|---|---|
| 0 | GREEN | Welle-2 cutover-PR can proceed to the Monday Pilot-VM Live-Smoke per ADR-0065 §Verifikations-Plan. The JSON envelope is admissible as cutover-PR evidence. If Welle-1 smoke is also GREEN, proceed to the doppel-cutover Live-Smoke per ADR-0066 §KW-24-Sequencing. |
| 1 | CAUTION | At least one caution-severity check failed (A3 latency drift, A4 component-count drift, A6 SVID-fixture drift). The engine-emission substance is intact (backend-flip + parity-hash + rollback all OK). **Investigate before the Monday Live-Smoke**: latency drift may indicate Rust-binary build-flag drift; component-count drift may indicate engine-inventory drift since the ADR-0066 baseline; A6 drift means the canonical encoder shifted (Tomás-Zone-K cross-review pre-empt). Escalate to Tomás (Matrix-Lead) for go/no-go on the doppel-cutover; ADR-0066 §KW-24-Rollback-Coupling pauses *both* waves on a caution band. |
| 2 | ROLLBACK_RECOMMENDED | At least one blocker-severity check failed (A1, A2, A5, or R1). Do not proceed to the Monday Live-Smoke. Open a substance-bug-issue (label `welle-2-smoke-fail`), eskaliert to Priya (CTO) per ADR-0065 §Rollback-Procedure Step 1. The doppel-cutover halts; Welle-1 smoke is also frozen until Welle-2 is resolved. |
| (3+) | (not used by smoke) | I/O failure (`--output` not writable) is reported as exit 2 by convention — operator must consume the evidence before proceeding. |

## Envelope shape

The smoke emits a JSON envelope to `--output` (or stdout). The
top-level keys are:

```text
schema                    "wakir.phase-3c.welle-2-cutover-smoke/1"
timestamp_utc             POSIX-epoch integer
welle                     2
focus_component           "svid_workload_identity"
focus_env_var             "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND"
engine_boot_components    list of in-place component names (default 9)
expected_components       int (CLI arg)
boots_per_phase           int (CLI arg)
latency_tolerance_pct     int (CLI arg)
phases                    { "pre_cutover_python_baseline": {...},
                            "post_cutover_rust":          {...},
                            "rollback_python":            {...} }
asserts                   { A1, A2, A3, A4, A5, R1, A6 → {passed, severity, ...} }
exit_code                 0 | 1 | 2
band                      "GREEN" | "CAUTION" | "ROLLBACK_RECOMMENDED"
```

Each `phases[*]` sub-record carries `boots`, `decision_count`,
`focus_p95_latency_us`, `parity_hash` (raw, including
`chosen_backend`), and `focus_parity_hash_normalised` (the A2-relevant
projection, with `chosen_backend` stripped).

The A6 record additionally carries `skipped` (bool) and
`recomputed` (list of `{name, baseline, recomputed, match}` per
fixture) so operators can pinpoint exactly which fixture drifted.

## Hermeticity contract

The smoke is **stdlib-only** at the engine-emission level. The
optional A6 fixture-parity check imports
`wirelang.identity.svid_workload_identity_canonical` and reads
`tests/fixtures/svid-workload-cross-lang/fixtures.json`; both are
**gracefully skipped** (with `skipped=true, passed=true`) when
unavailable. The smoke never:

* Invokes the real Rust binary (`_binary_available` is stubbed to
  always-true; the smoke focuses on the backend-switch behaviour, not
  the binary-deployment posture — that's a separate Quadlet-Installer
  prerequisite per ADR-0065 §Trigger-Bedingung-3).
* Talks to NATS, the Anthropic API, or any container runtime.
* Mutates `os.environ` (the engine sees a private mapping).

The real-resolver path (`resolve_svid_workload_identity_backend`
from PR #191 — `wirelang.persona_engine.rust_backend_switch`) **is**
exercised end-to-end when the wirelang package is importable. Tests
inject a fully-stubbed resolver module for hermetic CI lanes.

## Real-resolver verification

`Selin-Tag-35` ran the smoke locally against the real PR #191
resolver:

```bash
PYTHONPATH=$(pwd) python3 \
  scripts/phase-3c/welle-2-svid-workload-identity-cutover-smoke.py \
  --boots-per-phase 4
# exit=0 (GREEN); A1/A2/A3/A4/A5/R1/A6 all passed; A6 reports
# "all 5 svid fixtures byte-equal" against the PR #224 pins.
```

The five PR #224 fixture-baseline SHA-256 values recompute byte-equal
under the real `wirelang.identity.svid_workload_identity_canonical`
module:

```
f01-empty-identity-set        44229ea7…44a7bd  (match)
f02-single-org-single-spiffe  75734083…cb6ee5a3 (match)
f03-multi-org-cross-mapping   67891af4…f68518  (match)
f04-key-rotation-svid-replay  ef75d1eb…fd66a05 (match)
f05-expired-svid-rejection    0e61d186…d72fd1  (match)
```

This pins the Welle-2 substrate-level cross-lang invariant the Rust
pendant in `wirelang-rust/crates/persona-engine-svid-workload-identity`
must hit byte-for-byte once it ships a `FetchX509SVID` runtime.

## Welle-3..7 forward-compat

The script's focus-component / focus-env-var / engine-boot-components
constants are top-level module symbols. Future Welle-N cutover-smokes
can be written by copying this file and re-pointing those constants
plus the A6-substrate-probe (each wave with cross-lang fixtures will
have its own canonical-snapshot module). The asserts-evaluation logic
is component-agnostic except for the A2 parity-hash projection (uses
the focus-component name verbatim) and A6 (SVID-specific by design;
remove or replace for Welle-3+).

## Cross-references

* **ADR-0065** §Verifikations-Plan (decision matrix derives from
  §AC-1..§AC-5 and §Rollback-Procedure).
* **ADR-0066** §KW-24-Sequencing + §KW-24-Rollback-Coupling — pins
  Welle-1 + Welle-2 as the parallel KW-24 doppel-cutover, forbids
  partial cutover.
* **PR #170** Anchor-Emitter Cross-Lang fixtures (Tag-23) — A2
  parity-hash references this as substrate-level oracle.
* **PR #179** BackendDecision Observability (Tag-24) — A3 latency
  tolerance derives from the same percentile machinery this script
  reuses (`_nearest_rank_percentile`).
* **PR #191** SVID-Workload-Identity Rust-Default Backend Resolver
  (Tag-25, `7e2defb`) — the real resolver the smoke exercises.
* **PR #196** SVID-Workload-Identity Welle-2 Validation Workflow
  (`2a33a8c`) — the CI lane that consumes this smoke.
* **PR #200** federation_resolver wire-in (Tag-30, `1ea7a60`) — the
  9th BackendDecision; default `--expected-components 9` tracks this.
* **PR #201** SVID-Workload-Identity Container-Image-Build-Pipeline
  (Tag-29, `cddce13`) — the Welle-2 Quadlet image.
* **PR #224** SVID-Workload-Identity Cross-Lang Pins (Tag-33,
  `de47cb3`) — the substrate-level A6 oracle.
* **PR #230** Welle-1 v907_verify Cutover-Smoke (Tag-34, `53af6ac`) —
  the sibling script; the operator runs both back-to-back in KW-24.
* **`docs/phase-3c/welle-1-cutover-smoke.md`** — the Welle-1 runbook;
  read alongside this one during the doppel-cutover.

---

_— Selin Çelik (Persona-Engine), Tag-35, 2026-05-18._
