# Phase-3c Welle-7 Cutover-Smoke Runbook (`recovery_workflow` / `recovery`)

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), Tomás Reinhart (Matrix-Lead, Zone K), Henrik Voss (Caution-Owner) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md), [0066](../../decisions/0066-phase-3c-doppel-cutover-acceleration-kw24.md) |
| Script (Python) | [`scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py`](../../scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py) |
| Script (Bash wrapper) | [`scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh`](../../scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh) |
| Tests | [`tests/phase_3c/test_welle_7_cutover_smoke.py`](../../tests/phase_3c/test_welle_7_cutover_smoke.py) (17 tests) |
| Sibling | [`docs/phase-3c/welle-6-cutover-smoke.md`](welle-6-cutover-smoke.md), [`docs/phase-3c/welle-5-cutover-smoke.md`](welle-5-cutover-smoke.md) |

## Purpose

This runbook describes the **End-to-End Cutover-Smoke** for
ADR-0066 Welle-7 (`recovery_workflow`, in-repo short form
`recovery`), the **KW-27 Doppel-Welle** that runs **in parallel
with Welle-6** (`subscribe_loop`). Welle-7 is the **final Doppel-
Welle of Phase-3** (Phase-3-Ende together with Welle-6) — closing
the seven-Welle sequence.

`recovery_workflow` (`RecoveryWorkflow`) is the R1..R4
orchestrator that brings a despawned/crashed persona back to
`running` (spec §3.7.4):

- **R1 Detect** — classify the trigger (closed enum of three:
  `CrashDetected`, `DespawnMidOperation`, `StateCorruption`).
- **R2 Reload** — restore state from persistence backing.
- **R3 Re-register** — refresh SPIFFE SVID via workload-API.
- **R4 Resume** — transition Quadlet container to `active`.

At the runtime level, R2-Reload reads from `state_backing`
(Welle-4, already cutovert in KW-26) and R3-Re-register
coordinates with the SVID workload-identity substrate. The
Welle-6 partner (`subscribe_loop`) is the NATS message pump that
must coordinate with recovery during R2 to drain in-flight
messages before state mutation.

Tomás (Zone K) flagged the joint cutover as a
**Cross-Modul-Drift-Risk** during the ADR-0066 review: when both
modules flip from Python to Rust during the same KW-27 window,
any drift in their joint contract (R1-detection signal source,
RecoveryOutcome byte-shape, R4-Resume callback semantics) will
manifest as cross-modul recovery storms or message loss that no
single-module smoke can catch.

## Naming note

The Auftrag refers to the resolver as
`resolve_recovery_workflow_backend` but the in-repo function name
is `resolve_recovery_backend` (matching the BackendDecision-domain
short form `recovery`). The smoke binds to the short-form name;
the long-form `recovery_workflow` is surfaced only in the
`focus_component_long` envelope field for operator readability.

## Recovery-R1..R4-Drill (A6) and Cross-Modul-Drift (A7)

The Welle-7 smoke adds **two** Welle-7-specific asserts on top of
the Welle-1/2/3 shape (A1..A5 + R1):

* **A6 recovery-r1-r4-drill (hermetic R1..R4 mock-drill over
  cutover window):** the smoke captures a deterministic
  RecoveryOutcome envelope walking the full R1 -> R2 -> R3 -> R4
  spec §3.7.4 happy-path **BEFORE the cutover-step constructs the
  `PHASE_POST` env-map**. After the cutover (engine-reboot with
  `WAKIR_RECOVERY_BACKEND=rust`), the smoke re-emits the same
  RecoveryOutcome via the Python authority a second time and
  asserts byte-equality of the JCS-canonical bytes.
  **Additionally**, the smoke verifies that every phase result in
  the recomputed outcome belongs to the spec's closed phase
  enumeration `("R1", "R2", "R3", "R4")` AND that the ordering is
  preserved — no phase reordering, no out-of-spec phase labels.
  Severity: **caution**. A hash mismatch or phase-ordering drift
  here signals Python RecoveryOutcome encoder drift between pre
  and post, which is a Tomás-Zone-K cross-modul drift signal, not
  a Pilot-VM-cutover blocker.

* **A7 cross-modul-drift-to-Welle-6 (recovery_workflow × subscribe_loop):**
  verifies that the `subscribe_loop` env-var stays at `python` in
  `PHASE_POST` and that the per-boot `subscribe_loop`
  BackendDecision `chosen_backend` field matches the env-var
  requested-value byte-for-byte in **every** phase. This is the
  cross-modul invariant: the recovery cutover MUST NOT silently
  force the subscribe_loop component into a different backend
  (the parallel-Welle joint-cutover concern). Severity:
  **blocker** — a fail here means recovery's resolver leaked into
  the subscribe_loop decision path, which would invalidate the
  parallel-Welle isolation contract.

A7 is **symmetric to Welle-6's A7**: Welle-6's A7 checks that
subscribe_loop's cutover does not leak into recovery; Welle-7's
A7 checks that recovery's cutover does not leak into
subscribe_loop. Together they pin the parallel-Welle isolation
contract bidirectionally.

## State-Backing-Awareness + FSM-Awareness pre-checks

Per Auftrag-Tag-39, recovery reads from `state_backing` (Welle-4,
already cutovert in KW-26). By KW-27 the state_backing substrate
is stable on Rust-default. state_backing has a three-valued enum
(`python`, `rust_inmemory`, `rust_natskv`); the Welle-4 cutover
defaults to `rust_inmemory`, so the smoke pins
`WAKIR_STATE_BACKING_BACKEND=rust_inmemory` in every phase to
reflect the realistic post-KW-26 runtime posture. The envelope's
`state_backing_post_cutover_state` field confirms state_backing
is in the expected state.

Similarly, FSM (Welle-5) was cutovert in KW-26; the smoke pins
`WAKIR_FSM_BACKEND=rust` in every phase, and the envelope's
`fsm_post_cutover_state` field confirms FSM is rust.

The Welle-7 cutover must NOT be started before state_backing
**and** FSM are stable on Rust-default — both are upstream
substrates that recovery depends on.

## Substrate inventory

| Substrate | PR | Commit | Role |
|---|---|---|---|
| recovery Rust-Default-Resolver substrate | [#135](https://github.com/wakir-labs/wakir-runtime/pull/135) | Tag-13 | The recovery substrate the resolver dispatches to. |
| recovery Rust-Default-Resolver wiring | [#167](https://github.com/wakir-labs/wakir-runtime/pull/167) | Tag-17 | The upstream `resolve_recovery_backend` the smoke calls directly. |
| recovery Cross-Lang Pins | [#176](https://github.com/wakir-labs/wakir-runtime/pull/176) | Tag-20 | RecoveryOutcome cross-lang fixture vectors A6 cross-checks. |
| subscribe_loop Rust-Default-Resolver (ENV-gated) | [#181](https://github.com/wakir-labs/wakir-runtime/pull/181) | Tag-22 | Welle-6 partner resolver (used in A7 cross-modul-drift check). |
| Welle-6 (subscribe_loop) Cutover-Smoke | this Tag-39 PR | — | Pattern-parity sibling; Welle-7 mirrors the structural shape. |
| state_backing (Welle-4 KW-26 prereq) | [#245](https://github.com/wakir-labs/wakir-runtime/pull/245) | Tag-37 | Cutovert in KW-26; smoke pins to rust. |
| fsm (Welle-5 KW-26 prereq) | [#249](https://github.com/wakir-labs/wakir-runtime/pull/249) | Tag-38 | Cutovert in KW-26; smoke pins to rust. |

## Resolver-provenance (recovery always upstream)

Welle-7 uses the **real upstream resolver**
`resolve_recovery_backend` directly. The resolver has been in
baseline since PR #167 (Tag-17). The smoke imports it via
`_import_resolver()` and never constructs a shim for the focus.
The `resolver_provenance` field in the envelope reports
`"upstream"` for `recovery` in every run.

## Asserts

| Assert | Severity | Description |
|---|---|---|
| **A1** `backend_flip` | blocker | post-cutover recovery `chosen_backend` == `rust` across all PHASE_POST boots. |
| **A2** `cross_lang_parity_hash` | blocker | structural-projection parity-hash identical between PHASE_POST and PHASE_ROLLBACK. |
| **A3** `latency_within_tolerance` | caution | post-cutover P95 latency <= pre-baseline P95 × (1 + tolerance%). |
| **A4** `decision_count_in_place` | caution | total post-cutover decisions == `expected_components × boots_per_phase`. |
| **A5** `fallback_clean` | blocker | no `fallback_reason` populated on recovery PHASE_POST records. |
| **R1** `rollback_to_python` | blocker | rollback-phase recovery `chosen_backend` == `python`. |
| **A6** `recovery_r1_r4_drill` | caution | RecoveryOutcome JCS bytes byte-stable across pre/post via Python authority AND phase ordering preserves spec §3.7.4 enumeration. |
| **A7** `cross_modul_drift_welle_6_subscribe_loop` | blocker | subscribe_loop `chosen_backend` == `python` across all PHASE_POST records (parallel-Welle isolation, symmetric to Welle-6 A7). |

Exit-code triad:

| Exit | Band | Meaning |
|---|---|---|
| `0` | GREEN | All asserts pass. Cutover proceeds. |
| `1` | CAUTION | At least one caution-severity assert failed. |
| `2` | ROLLBACK_RECOMMENDED | At least one blocker-severity assert failed. |

## Operator invocation

### GREEN-path (default)

```bash
python3 scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py \
    --output out/welle-7-smoke.json

# Or via bash wrapper:
bash scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh \
    --output out/welle-7-smoke.json
```

### Higher boots for tighter percentile sample (CI hot-path)

```bash
python3 scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py \
    --boots-per-phase 12 \
    --latency-tolerance-pct 100 \
    --output out/welle-7-smoke.json
```

### Skip A6 (e.g. import-path-restricted CI or missing rfc8785 wheel)

```bash
python3 scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.py \
    --skip-recovery-drill-parity \
    --output out/welle-7-smoke.json
```

Note: the smoke gracefully falls back to a smoke-internal JSON-
canonical hash when the wirelang public API's
`recovery_outcome_jcs_bytes` raises (e.g. rfc8785 wheel absent),
so A6 does NOT require the rfc8785 wheel to be importable. The
fallback path keeps the hash byte-stable across the pre/post
window. A7 cross-modul-drift is independent of A6 and always runs.

## Decision matrix

| A1 | A2 | A5 | A7 | R1 | A3 | A4 | A6 | Exit | Operator-Action |
|---|---|---|---|---|---|---|---|---|---|
| pass | pass | pass | pass | pass | pass | pass | pass | **GREEN** | Proceed to live-smoke. |
| pass | pass | pass | pass | pass | **fail** | pass | pass | **CAUTION** | A3 latency: bump `--latency-tolerance-pct 100`. |
| pass | pass | pass | pass | pass | pass | pass | **fail** | **CAUTION** | A6 RecoveryOutcome encoder drift OR phase-ordering violation. Check `phase_ordering_violations` field — empty means pure byte-drift, populated means spec-table corruption. |
| **fail** | * | * | * | * | * | * | * | **ROLLBACK** | A1: post-cutover recovery is not rust. |
| * | * | * | **fail** | * | * | * | * | **ROLLBACK** | A7: **recovery cutover leaked into subscribe_loop path**. KW-27 Doppel-Welle isolation broken. Roll back recovery AND Welle-6. |

## Cross-Modul-Drift Mitigation to Welle-6 (symmetric A7)

The A7 assert is the **engineering substance** of the KW-27
Doppel-Welle mitigation, viewed from the Welle-7 side. The risk
scenario Tomás flagged is **"Welle-7's cutover machinery silently
changes Welle-6's behaviour"** — env-var clobber (e.g. recovery
resolver writing to `WAKIR_SUBSCRIBE_LOOP_BACKEND`), boot-order
coupling (recovery binary mutates process-wide state that
subscribe_loop reads), or shared cache (backend-resolution cache
overwrite). A7 catches the observable consequence:
subscribe_loop's `chosen_backend` in PHASE_POST.

Welle-6 (`subscribe_loop`) runs its own smoke in parallel. The
Welle-6 smoke's A7 verifies recovery's stability under
subscribe_loop's cutover (the inverse leak direction). The two
smokes are independent (different focus-components, different
env-vars) but their joint passing is the operator-Sicht parallel-
Welle isolation contract.

## A6 Substrate-Level Test Coverage

The A6 assert combines two sub-axes that are tested independently:

* **Byte-stability:** the
  `test_a6_recovery_drill_caution_on_byte_drift` test constructs
  a stub canonical module that salts its serialised output after
  the baseline-capture call, producing a hash mismatch in the
  recompute. A6 must fire with `match=False`.
* **Phase-ordering trap:** the
  `test_a6_recovery_drill_caution_on_phase_ordering_violation`
  test feeds the smoke a hand-crafted outcome with phases out of
  spec order (R2 before R1). A6 must flag the violations in the
  `phase_ordering_violations` field.

Both sub-axes are caution-severity. The pairing pins the smoke's
A6 oracle: it detects encoder drift AND it detects spec-table
corruption.

## CI integration

The Welle-7 validation workflow (when wired) consumes the
existing acceptance steps plus the Cross-Modul-Stress-Test.
**This smoke is the local-hermetic precursor**, not a CI workflow
step. Operators wire it into pre-PR shell-gates via:

```bash
bash scripts/phase-3c/welle-7-recovery-workflow-cutover-smoke.sh \
    --output out/welle-7-smoke.json
```

GREEN -> proceed. CAUTION -> review the specific assert.
ROLLBACK -> do NOT proceed.

## Test reference

[`tests/phase_3c/test_welle_7_cutover_smoke.py`](../../tests/phase_3c/test_welle_7_cutover_smoke.py)
covers 17 hermetic scenarios. Run locally:

```bash
PYTHONPATH=. python3 -m pytest tests/phase_3c/test_welle_7_cutover_smoke.py -v
```

The test suite never imports the real wirelang package — every
test injects a stub `rust_backend_switch` module and a stub
`recovery_workflow_canonical` module via the `resolver_module=` /
`canonical_module=` kwargs.

## Henrik / Tomás Cross-Review checklist

Before merging the Welle-7 Pilot-VM cutover PR:

- [ ] A1..A5 + R1 + A6 + A7 all green on the local smoke (`out/welle-7-smoke.json` band=GREEN).
- [ ] Welle-6 smoke green in parallel (Henrik joint-verification — both A7 asserts must pass).
- [ ] `resolver_provenance.recovery` == `"upstream"` in the envelope.
- [ ] `cross_modul_drift_mitigation.subscribe_loop_chosen_backends_in_post_phase` == `["python"]`.
- [ ] `state_backing_post_cutover_state.state_backing_in_expected_post_kw26_state` == `true` (Welle-4 cutovert from KW-26, stable on rust).
- [ ] `fsm_post_cutover_state.fsm_in_expected_post_kw26_state` == `true` (Welle-5 cutovert from KW-26, stable on rust).
- [ ] `recovery_drill_integrity.spec_valid_recovery_phases` == `["R1", "R2", "R3", "R4"]`.
- [ ] `recovery_drill_integrity.baseline_phase_ordering_violations` == `[]` (the deterministic fixture uses spec-ordered phases).
- [ ] Pilot-VM live-smoke confirms `WAKIR_RECOVERY_BACKEND=rust` flips successfully.
- [ ] Rollback-Drill <=10 min per ADR-0065 §Rollback-SLA.
- [ ] Tomás (Zone K) signed off on the joint Welle-6+7 substrate-readiness (Phase-3-Ende sign-off).
- [ ] Henrik signed off on the Cross-Modul-Drift-Mitigation evidence (A7 assert ran and passed in BOTH smokes).

## Operator-Hand vs. Mira-Hand split

| Step | Owner | Notes |
|---|---|---|
| Smoke run (this script) | Mira-Hand (CI / pre-PR) | Hermetic, runs on every Welle-7 PR. |
| `--expected-components` value selection | Mira-Hand | Default 11 (Tag-38 baseline). |
| `--latency-tolerance-pct` selection | Mira-Hand or Operator | Default 20% per ADR-0065 §AC-2. |
| Pilot-VM live-smoke | Operator-Hand | Real binary, real ENV-flip on Quadlet, real engine reboot. |
| Rollback (ENV-unset) | Operator-Hand | Smoke's R1 assert verifies the code-path. |
| A6 phase-ordering-violation investigation | Selin + Tomás (Zone K) | If A6 fires with a populated `phase_ordering_violations` list, signals spec-table drift somewhere in the engine. |
| A7 cross-modul-drift investigation | Tomás (Zone K) + Henrik | If A7 fires, requires off-engine forensics. The Welle-6 A7 must be cross-checked in the same window. |

— Selin
