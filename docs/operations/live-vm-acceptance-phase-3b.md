<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Live-VM Acceptance — Phase-3b Backend-Matrix Lane

**Status:** Living operations document.
**Scope:** Operator companion for the Phase-3b backend-matrix
extension of `.github/workflows/live-vm-acceptance.yml` (Tag-18
Mini-Welle, 2026-05-17).
**Predecessor:** `docs/test-plans/phase-2-live-vm-acceptance.md`
(Tag-15/16 operator companion for the base lane).
**Related PR:** `wirelang/persona_engine/rust_backend_switch.py`
(PR #167, Tag-17 Mini-Welle) introduced the ENV-gated Rust-default
switches that this lane validates on a real Pilot-VM.

---

## 1. Why a separate Phase-3b lane exists

PR #167 wires two Rust crates (`persona-engine-recovery`,
`persona-engine-state-backing`) into the Python persona-engine via
ENV-gated subprocess-bridges:

* `WAKIR_RECOVERY_BACKEND=python|rust` selects the recovery
  workflow backend.
* `WAKIR_STATE_BACKING_BACKEND=python|rust_inmemory|rust_natskv`
  selects the state-backing backend.

The hermetic test suite (30 vectors in
`wirelang/tests/persona_engine/test_rust_backend_switch.py`) proves
the **switch itself** is correct. It cannot prove the **Rust
binaries** behave identically to their Python pendants on a real VM
with production-shaped storage, networking and SELinux context.

That live equivalence claim is what the Phase-3b backend-matrix lane
validates. The matrix re-runs the persona spawn → R1..R4 recovery →
state-backing roundtrip cycle once per `(recovery_backend ×
state_backing_backend)` permutation on the same Pilot-VM, then
asserts:

1. Every selected permutation reaches `status: ok`.
2. The `final_state_hash` value is **byte-identical** across every
   `ok`-status permutation — the cross-language Doppelbetrieb
   equivalence claim.
3. The recovery and state-backing **p95 latency** stays under the
   operator-supplied budget (`phase_3b_latency_budget_ms`, default
   1500 ms; the budget covers Rust subprocess-bridge cold-start).

When all three hold, Phase-3b acceptance for that workflow run is
PASS.

---

## 2. Lane topology

The Phase-3b extension adds two jobs to `live-vm-acceptance.yml`:

```
                +----------------------------+
                | live-vm-acceptance         |  (Tag-15, base lane)
                | (Operator-Hand dispatch)   |
                +----------------------------+
                              |
                              v  needs:
                +----------------------------+
                | live-vm-acceptance-        |  matrix:
                | phase-3b                   |   recovery_backend  x
                | (matrix-spawned)           |   state_backing_backend
                +----------------------------+
                              |
                              v  needs:
                +----------------------------+
                | live-vm-acceptance-        |  collects per-cell
                | phase-3b-aggregate         |  reports, enforces
                | (single job)               |  equivalence + budget
                +----------------------------+
```

Both new jobs gate themselves on the `recovery_backend != 'none'` OR
`state_backing_backend != 'none'` condition. When both inputs are
`none` (the default), only the base lane runs and the new jobs
no-op — preserving Tag-15/16 dispatch semantics for operators who
do not want Phase-3b validation in a given run.

---

## 3. Dispatch inputs (Phase-3b-specific)

| input | type | default | meaning |
|---|---|---|---|
| `recovery_backend` | choice | `none` | `none` = skip Phase-3b; `python` = only Python; `rust` = only Rust; `both` = matrix-both |
| `state_backing_backend` | choice | `none` | `none` = skip Phase-3b; `python` / `rust_inmemory` / `rust_natskv` = single backend; `both` = matrix-both |
| `phase_3b_latency_budget_ms` | string | `1500` | per-backend p95 budget (recovery + state-backing) in milliseconds |

The base-lane inputs (`target_vm`, `test_filter`, `peer_host`,
`skip_cosign_verify`) are unchanged. Their semantics carry over to
the Phase-3b jobs unmodified — the Phase-3b driver SSHes into the
same target VM as the base wrapper.

When `recovery_backend = both` and `state_backing_backend = both`,
the matrix expands to 2 × 3 = 6 permutations:

```
(python, python)
(python, rust_inmemory)
(python, rust_natskv)
(rust,   python)
(rust,   rust_inmemory)
(rust,   rust_natskv)
```

Cells that do not match the operator's selection are filtered out
inside each cell's `Decide should_run for this permutation` step
(see workflow source, the GitHub-Actions matrix can only be a
Cartesian product so per-axis filters live inside the cells).

---

## 4. The driver script

The matrix-cell calls `scripts/ci-live-vm-phase-3b-driver.sh` with
the following flags:

```
--target              <wakir-pilot|wakir-orbit|both>
--ssh-user            wakir-acceptance
--ssh-key             <runner-temp-path>
--recovery-backend    <python|rust>
--state-backing-backend <python|rust_inmemory|rust_natskv>
--latency-budget-ms   <int>
--report-json         <output-path>
```

The driver SSHes to the target, exports the two ENV-vars, spawns a
test persona, drives the four recovery vectors R1..R4, exercises a
snapshot / `restore_latest` / `atomic_swap_pinned_offset` roundtrip,
collects per-step latency, computes the final-state hash, and emits
a structured JSON report:

```json
{
  "target_vm":                "wakir-pilot",
  "recovery_backend":         "rust",
  "state_backing_backend":    "rust_natskv",
  "latency_budget_ms":        1500,
  "status":                   "ok",
  "final_state_hash":         "<64-hex-blake3>",
  "recovery_latency_ms_p50":  42,
  "recovery_latency_ms_p95":  187,
  "state_latency_ms_p50":     31,
  "state_latency_ms_p95":     142,
  "fallback_reason":          null
}
```

### Driver-not-present staging

The Tag-18 Mini-Welle ships the **workflow surface**. The driver
script itself (`scripts/ci-live-vm-phase-3b-driver.sh`) is a
follow-up sprint deliverable. When the driver is absent, each
matrix-cell emits a structured `driver-not-present` stub:

```json
{
  "target_vm":                "wakir-pilot",
  "recovery_backend":         "python",
  "state_backing_backend":    "python",
  "latency_budget_ms":        1500,
  "status":                   "driver-not-present",
  "final_state_hash":         null,
  "recovery_latency_ms_p50":  null,
  "recovery_latency_ms_p95":  null,
  "state_latency_ms_p50":     null,
  "state_latency_ms_p95":     null,
  "fallback_reason":          "ci-driver-not-yet-implemented"
}
```

The aggregate job recognises `driver-not-present` as a clean SKIP —
the workflow returns success but the operator sees a clear signal
that no real acceptance ran. This mirrors the Tag-15 Tag-17 staging
posture where the wrapper and the on-VM script landed in
separate sprints.

---

## 5. Aggregation contract

`live-vm-acceptance-phase-3b-aggregate` collects every per-cell
report and emits an aggregate summary:

```json
{
  "status":               "ok",
  "permutations_total":   6,
  "permutations_ok":      6,
  "permutations_skipped": 0,
  "permutations_failed":  0,
  "final_state_hashes":   ["<64-hex-blake3>"],
  "equivalence_class":    1,
  "latency_budget_ms":    1500,
  "latency_violations":   [],
  "reports":              [ ... per-cell JSON ... ]
}
```

Aggregate status transitions:

| status | meaning | exit code |
|---|---|---|
| `ok` | every `ok` report shares a single `final_state_hash`, no latency violations | 0 |
| `skipped-driver-not-present` | every report is `driver-not-present` (Tag-18 staging) | 0 |
| `fail` | one or more per-cell reports are `fail` | 1 |
| `fail-equivalence-break` | `ok` reports carry more than one distinct `final_state_hash` (cross-backend drift) | 1 |
| `fail-latency-budget` | one or more `ok` reports exceed the p95 budget | 1 |
| `no-reports` | matrix did not emit any report (lane misconfigured) | 1 |
| `unknown` | catch-all (should never fire under documented inputs) | 1 |

The `equivalence_class` count is the **operator's primary
acceptance signal**: a value of `1` means every backend agrees on
the final state; any other value means at least two backends
disagree and the Phase-3b cutover claim is broken.

---

## 6. Latency budget rationale

Default `phase_3b_latency_budget_ms = 1500`. The budget covers:

* **Rust subprocess-bridge cold-start.** Each Rust-backend
  permutation forks a CLI binary; cold-start dominates the first
  R1..R4 invocation in the matrix-cell. Subsequent invocations
  benefit from the OS page-cache and stay below 500 ms.
* **NATS-KV roundtrip on the `rust_natskv` permutation.** The
  state-backing path traverses NATS-KV; production NATS-KV reads
  on the Pilot-VM measure 80-300 ms p95.
* **Python interpreter spin-up on the `python` permutations.**
  The Python persona-engine carries `wirelang.persona_engine.engine`
  module-load overhead.

When the per-permutation p95 exceeds 1500 ms the lane fails with
`fail-latency-budget`. Operators triaging a budget failure should:

1. Check whether the Pilot-VM is under unrelated load (cosign
   keyless sign-push, image pull, peer-VM ping floods).
2. Confirm the Rust binary at `/opt/wakir/bin/wakir-persona-engine-*`
   matches the production-image-pin from
   `infra/persona-images-pinned.json`.
3. Re-run the lane with a higher budget (`3000` ms) to distinguish
   a transient overload from a substrate regression.

---

## 7. Operator runbook

### 7.1 Dispatch a Phase-3b-only validation run

GitHub UI → Actions → live-vm-acceptance → Run workflow with:

```
target_vm              = wakir-pilot
recovery_backend       = both
state_backing_backend  = both
phase_3b_latency_budget_ms = 1500
```

This re-runs the base lane (cheap), then expands the 2×3 matrix
on the same VM, then aggregates.

### 7.2 Single-backend regression triage

When a previous run flagged `fail-equivalence-break` and the
operator suspects the `rust + rust_natskv` permutation:

```
recovery_backend       = rust
state_backing_backend  = rust_natskv
phase_3b_latency_budget_ms = 1500
```

The matrix collapses to a single cell; the aggregate verdict is the
per-cell verdict.

### 7.3 Skip Phase-3b entirely (Tag-15/16 parity)

```
recovery_backend       = none
state_backing_backend  = none
```

The new jobs no-op; the lane behaves exactly as before Tag-18.

### 7.4 Verdict consumption

The aggregate summary lands as an artefact named
`phase-3b-aggregate-summary-<run-id>`. Operators consuming the
verdict programmatically should fetch this artefact and read
`aggregate-summary.json`:

```sh
gh run download <run-id> --name phase-3b-aggregate-summary-<run-id>
jq '.status, .equivalence_class, .latency_violations' aggregate-summary.json
```

---

## 8. Cross-Review anchors

* **PR #167** (Tag-17 Mini-Welle, ENV-gated Rust-default switches)
  — this lane is the Phase-3b production validation surface for
  the switches.
* **ADR-0058** (Pilot-Persona-Migrations-Plan) — §"Phase 4
  Cutover-Entscheidung". The Phase-3b equivalence verdict is one
  of the inputs to the Phase-3a → Phase-4 cutover decision.
* **Zone N** (QA × Henrik-Audit) — the aggregate summary JSON is
  evidence for the Doppelbetrieb cross-language equivalence
  claim. Henrik samples a Phase-3b run per audit window.
* **Zone J** (Persona-Engine × Container-Substrate) — the lane is
  Persona-Engine-substance running under Kai-owned Container-Infra;
  Selin and Kai cross-review the driver-script PR when it lands.
* **`feedback_sandbox_host_trennung.md`** (Mira-Memory) — the
  hermetic claude-dev Sandbox cannot reach `192.168.178.*`.
  Phase-3b inherits the base-lane SSH-precheck and fails closed
  when the secret is absent.

---

## 9. Out of scope (Tag-18)

* ~~`scripts/ci-live-vm-phase-3b-driver.sh`~~ — landed Tag-19 (this
  follow-up). The driver is the matrix-cell hand-off implementation
  that fulfils the §4 contract. The workflow keeps its inline
  `driver-not-present` stub-emit as a defence-in-depth safety net
  for branches that predate Tag-19 (see
  `live-vm-acceptance.yml:648` `if [[ -x "${DRIVER}" ]]; then`).
* Real-VM bring-up in CI. The hermetic Sandbox cannot reach the
  Pilot-VM. The Phase-3b lane is Operator-Hand-dispatch only,
  identical to the base lane. The driver itself supports an
  `--mode=self-test` surface so its CLI + verdict-emit can be
  exercised hermetically via `WAKIR_PHASE_3B_MOCK_*` ENV-vars
  (see `tests/scripts/test_ci_live_vm_phase_3b_driver.py`).
* Automatic cross-language equivalence assertion in the Tag-15/16
  hermetic test surface. The hermetic surface already pins
  `final_state_hash` via PR #135 / #140 cross-language fixtures;
  Phase-3b validates the same claim on a real VM.

---

## 10. Tag-19 driver follow-up — verdict-status codomain narrowing

The Tag-18 workflow YAML §4 originally hinted at a richer
verdict-status codomain
(`{ok, fail, fail-latency-budget, fail-driver-error,
driver-not-present}`). The Tag-19 driver implementation discovered
that the per-permutation verdict-step
(`live-vm-acceptance.yml:707-724`) only accepts three tokens
(`{ok, fail, driver-not-present}`) before tripping its
`Unknown report status` hard-error branch.

The driver therefore narrows the emitted verdict-status to that
three-token codomain and surfaces the richer failure-mode
discriminator via `backend_decision_record.fail_subkind`:

| status               | fail_subkind     | exit-code | meaning                                            |
| -------------------- | ---------------- | --------- | -------------------------------------------------- |
| `ok`                 | `null`           | 0         | clean pass                                         |
| `fail`               | `latency-budget` | 2         | p95 exceeded `--latency-budget-ms`                 |
| `fail`               | `driver-error`   | 3         | SSH/remote-driver exec failure                     |
| `fail`               | `on-vm`          | 4         | remote acceptance script returned status==fail     |
| `driver-not-present` | `null`           | 0         | remote driver binary not yet deployed              |

The aggregate-job consumes `status` only; the exit code is the
operator-side richer signal. Auditors (Henrik's sample-audit lane,
Zone N) can read `backend_decision_record.fail_subkind` to
distinguish the failure-modes without re-running the lane.

— Kai
