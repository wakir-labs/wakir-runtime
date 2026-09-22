<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Live-VM Acceptance — Phase-3b Backend-Matrix Lane

**Status:** Living operations document — read section 0 first.
**Scope:** Operator companion for the Phase-3b backend matrix, driven
by hand through `scripts/ci-live-vm-phase-3b-driver.sh`.
**Predecessor:** `docs/test-plans/phase-2-live-vm-acceptance.md`
(operator companion for the base acceptance).
**Related PR:** `wirelang/persona_engine/rust_backend_switch.py`
(PR #167) introduced the ENV-gated Rust-default switches that this
matrix validates on a real Pilot-VM.

---

## 0. What changed on 2026-09-22, and what this document is now

This document was written as the companion to a CI lane: a matrix job
that expanded the backend permutations, and an aggregate job that
collected the per-cell reports, enforced final-state-hash equivalence
and applied the latency budget. **That lane no longer exists.** It aimed
a hosted runner at a private-network address and read its credentials
from Actions secrets the repository does not hold; it was never
dispatched once in four months, and it was withdrawn under ADR-0077.

What survives is the part that never needed a workflow:

* the **driver** (`scripts/ci-live-vm-phase-3b-driver.sh`), which
  reaches the target over SSH from an operator-controlled host and
  writes one report per invocation;
* the **contracts** — the driver flags in section 4, the report shape in
  section 4, the aggregation rules in section 5, the latency budget in
  section 6.

What an operator now does instead of dispatching: expand the matrix by
invoking the driver once per permutation, then apply section 5 to the
reports by hand or with a script of their own. Nothing aggregates
automatically, and no status is reported anywhere unless somebody
reports it.

**Neither the matrix nor the driver has ever been executed against a
real VM.** The lane that would have done it never ran, and no operator
has run the driver by hand. Read the rest of this document as a design
that is written down and untried, not as a procedure with a track
record. The acceptance that does have a track record is the base one —
`scripts/federation-live-vm-acceptance.sh`, run on the node itself,
three times on 2026-09-21/22, and it failed there.

---

## 1. Why a separate Phase-3b run exists

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

That live equivalence claim is what the Phase-3b backend matrix
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

## 2. Run topology

```
   base acceptance on the node          one driver run per permutation
   (proven; run first)                  (never run; from operator host)
 +-----------------------------+      +------------------------------+
 | federation-live-vm-         |  ->  | ci-live-vm-phase-3b-driver   |
 | acceptance.sh, as root on   |      | --recovery-backend X         |
 | the substrate node          |      | --state-backing-backend Y    |
 +-----------------------------+      | --report-json <path>         |
                                      +------------------------------+
                                                     |
                                                     v
                                        section 5, applied by the
                                        operator to the collected
                                        reports
```

Order matters for the same reason it did when a job enforced it: a
backend-equivalence claim over a substrate that does not pass its base
acceptance is a claim about nothing. Run the base acceptance first and
read its verdict before expanding the matrix.

There is no longer a "skip Phase-3b" setting, because there is no run
to opt out of: not invoking the driver is the default.

---

## 3. The matrix an operator expands

The axes are the two backend switches. The full matrix is 2 × 3 = 6
permutations, one driver invocation each:

```
(python, python)
(python, rust_inmemory)
(python, rust_natskv)
(rust,   python)
(rust,   rust_inmemory)
(rust,   rust_natskv)
```

There is no dispatch form to fill in and no per-axis filter to
configure: the operator runs the permutations they want and leaves out
the ones they do not. A partial matrix is legitimate for triage
(section 7.2) but does not support the equivalence claim — that claim
needs every permutation whose backends it is about.

The per-backend p95 latency budget, previously a dispatch input, is now
the `--latency-budget-ms` flag. Its default remains 1500 ms; the
reasoning is in section 6.

The target VM, SSH user and key are driver flags (section 4), and point
at the same nodes the base acceptance runs on.

---

## 4. The driver script

Invoke `scripts/ci-live-vm-phase-3b-driver.sh` with the following
flags — one invocation per permutation:

```
--target              <wakir-pilot|wakir-orbit|both>
--ssh-user            wakir-acceptance
--ssh-key             <path to the operator's key>
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

### The `driver-not-present` status

The status dates from a staging posture: the lane surface landed one
sprint before the driver did, and a cell with no driver emitted a
structured stub rather than a silent pass. The stub shape is kept
because the distinction it encodes is the one that matters when reading
reports — "nothing ran here" must not look like "ran and passed":

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

Section 5 treats an all-`driver-not-present` report set as a SKIP, not
a pass. Since the aggregation is now done by the reader, this is the
rule the reader applies: a report set that contains such a status has
told you where it is not evidence.

---

## 5. Aggregation contract

This section used to describe what an aggregate job did. It now
describes what the operator has to do with the collected reports — the
rules are unchanged, the enforcement is a hand. Collect the per-run
reports and derive the same summary:

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

Aggregate status values, and how to reach them:

| status | meaning | exit code |
|---|---|---|
| `ok` | every `ok` report shares a single `final_state_hash`, no latency violations | 0 |
| `skipped-driver-not-present` | every report is `driver-not-present` (staging) | 0 |
| `fail` | one or more per-cell reports are `fail` | 1 |
| `fail-equivalence-break` | `ok` reports carry more than one distinct `final_state_hash` (cross-backend drift) | 1 |
| `fail-latency-budget` | one or more `ok` reports exceed the p95 budget | 1 |
| `no-reports` | no report was produced at all — which now means nobody ran the driver, and is the state this matrix has been in since it was written | 1 |
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
  R1..R4 invocation of each permutation. Subsequent invocations
  benefit from the OS page-cache and stay below 500 ms.
* **NATS-KV roundtrip on the `rust_natskv` permutation.** The
  state-backing path traverses NATS-KV; production NATS-KV reads
  on the Pilot-VM measure 80-300 ms p95.
* **Python interpreter spin-up on the `python` permutations.**
  The Python persona-engine carries `wirelang.persona_engine.engine`
  module-load overhead.

When the per-permutation p95 exceeds 1500 ms the driver exits with
`fail` / `fail_subkind: latency-budget`. Operators triaging a budget
failure should:

1. Check whether the Pilot-VM is under unrelated load (cosign
   keyless sign-push, image pull, peer-VM ping floods).
2. Confirm the Rust binary at `/opt/wakir/bin/wakir-persona-engine-*`
   matches the production-image-pin from
   `infra/persona-images-pinned.json`.
3. Re-run with a higher `--latency-budget-ms` (`3000`) to distinguish
   a transient overload from a substrate regression.

---

## 7. Operator runbook

### 7.1 A full backend-equivalence run

Run the base acceptance on the node first and read its verdict
(`scripts/federation-live-vm-acceptance.sh`). Then, from the operator
host, one driver invocation per permutation against the same VM:

```sh
for rec in python rust; do
  for sb in python rust_inmemory rust_natskv; do
    bash scripts/ci-live-vm-phase-3b-driver.sh \
      --target wakir-pilot \
      --ssh-user wakir-acceptance \
      --ssh-key "$KEY" \
      --recovery-backend "$rec" \
      --state-backing-backend "$sb" \
      --latency-budget-ms 1500 \
      --report-json "reports/$rec-$sb.json"
  done
done
```

Then apply section 5 to `reports/*.json`. The value to read first is
the number of distinct `final_state_hash` values across the `ok`
reports: one means the backends agree, anything else means they do not.

### 7.2 Single-backend regression triage

When a previous set showed an equivalence break and the suspicion falls
on one permutation, run that one alone:

```sh
bash scripts/ci-live-vm-phase-3b-driver.sh \
  --target wakir-pilot --ssh-user wakir-acceptance --ssh-key "$KEY" \
  --recovery-backend rust --state-backing-backend rust_natskv \
  --latency-budget-ms 1500 --report-json reports/triage.json
```

A single report is its own verdict. It supports a triage conclusion, not
an equivalence claim — see section 3.

### 7.3 Verdict consumption and keeping the evidence

The reports are the evidence and nothing stores them for you. Keep the
per-permutation JSON files together with the base acceptance log from
the same session, under a path that names the date and the commit the
substrate was running.

```sh
jq -s 'map(.status)          | unique' reports/*.json
jq -s 'map(select(.status=="ok") | .final_state_hash) | unique' reports/*.json
jq -s 'map(select(.recovery_latency_ms_p95 > 1500))' reports/*.json
```

The three lines are section 5's status set, equivalence class and
latency violations. An operator who runs the matrix and does not keep
the output has produced no evidence — the same defect as a gate that
reports without measuring, arrived at from the other side.

---

## 8. Cross-Review anchors

* **PR #167** (mini wave, ENV-gated Rust-default switches)
  — this matrix is the Phase-3b production validation surface for
  the switches, and it has not been exercised.
* **ADR-0058** (Pilot-Persona-Migrations-Plan) — §"Phase 4
  cutover-Entscheidung". The Phase-3b equivalence verdict is one
  of the inputs to the Phase-3a → Phase-4 cutover decision.
* **Zone N** (QA × Audit) — the collected reports are the evidence for
  the Doppelbetrieb cross-language equivalence claim. Internal audit
  samples a Phase-3b run per audit window; as of 2026-09-22 there is no
  run to sample, which is itself the finding.
* **Zone J** (Persona-Engine × Container-Substrate) — the matrix is
  Persona-Engine substance running on infrastructure-owned container
  infra; persona-engine engineering and infrastructure engineering
  cross-review changes to the driver script.
* **`feedback_sandbox_host_trennung.md`** (Memory) — the hermetic
  claude-dev sandbox cannot reach the substrate network. The driver
  fails closed when it cannot reach the target, and `--mode=self-test`
  is the only surface a sandbox may use.
* **ADR-0077** (2026-09-22) — withdrew the CI lane this document was
  written for. Section 0 states what that changed.

---

## 9. Out of scope

* Real-VM bring-up in CI. There is no CI path to a real VM in this
  repository and, per ADR-0077, no plan to build one: the capability
  lives in the operator's hand and a self-hosted runner was weighed
  and declined. The driver supports `--mode=self-test` so its CLI and
  verdict-emit can be exercised hermetically via
  `WAKIR_PHASE_3B_MOCK_*` ENV-vars (see
  `tests/scripts/test_ci_live_vm_phase_3b_driver.py`); that surface
  proves the driver's shape and nothing about a substrate.
* Automatic cross-language equivalence assertion in the/16
  hermetic test surface. The hermetic surface already pins
  `final_state_hash` via PR #135 / #140 cross-language fixtures;
  Phase-3b validates the same claim on a real VM.

---

## 10. Verdict-status codomain narrowing

An earlier draft hinted at a richer verdict-status codomain
(`{ok, fail, fail-latency-budget, fail-driver-error,
driver-not-present}`). The driver implementation found that the
per-permutation verdict step of the (since withdrawn) lane accepted
only three tokens (`{ok, fail, driver-not-present}`) before tripping
its `Unknown report status` hard-error branch. The narrow codomain
outlived the step that forced it, because the reports and this
contract are written against it.

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

Section 5's aggregation consumes `status` only; the exit code is the
richer signal at the point of invocation. Auditors (internal audit's
sample-audit lane, Zone N) read `backend_decision_record.fail_subkind`
to tell the failure modes apart without re-running anything.
