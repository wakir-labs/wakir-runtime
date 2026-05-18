# Phase-3c Welle-6 Cutover-Smoke Runbook (`subscribe_loop`)

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), Tomás Reinhart (Matrix-Lead, Zone K), Henrik Voss (Caution-Owner) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md), [0066](../../decisions/0066-phase-3c-doppel-cutover-acceleration-kw24.md) |
| Script (Python) | [`scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py`](../../scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py) |
| Script (Bash wrapper) | [`scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh`](../../scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh) |
| Tests | [`tests/phase_3c/test_welle_6_cutover_smoke.py`](../../tests/phase_3c/test_welle_6_cutover_smoke.py) (17 tests) |
| Sibling | [`docs/phase-3c/welle-5-cutover-smoke.md`](welle-5-cutover-smoke.md), [`docs/phase-3c/welle-7-cutover-smoke.md`](welle-7-cutover-smoke.md) |

## Purpose

This runbook describes the **End-to-End Cutover-Smoke** for
ADR-0066 Welle-6 (`subscribe_loop`), the **KW-27 Doppel-Welle**
that runs **in parallel with Welle-7** (`recovery_workflow`).
Welle-6 is the **final Doppel-Welle of Phase-3** (Phase-3-Ende
together with Welle-7).

`subscribe_loop` (`NatsSubscribeLoop`) is the NATS message pump
that delivers prompt envelopes to the persona-engine and emits
ack-records back (spec §3.7.6, Sprint-Pengine-10 OI-PEFR-6). The
Welle-7 partner (`recovery_workflow`) is the R1..R4 orchestrator
(spec §3.7.4). At the runtime level, the subscribe-loop is the
**observer-of-truth** for "is the persona alive?": it sees the
prompt-envelope traffic that signals an active persona-session.
The recovery-workflow, on entry, must coordinate with the
subscribe-loop to drain in-flight messages before R2-Reload
mutates state.

Tomás (Zone K) flagged the joint cutover as a
**Cross-Modul-Drift-Risk** during the ADR-0066 review: when both
modules flip from Python to Rust during the same KW-27 window,
any drift in their joint contract (ack-record byte-shape, lag-
sample emission rate, R1-detection signal source) will manifest
as cross-modul recovery storms or message loss that no single-
module smoke can catch.

The smoke is **not** the Monday Live-Smoke (that one is Pilot-VM
operator-hand-territory). It is the local-hermetic precursor: it
exercises the full pre-cutover / cutover-step / post-cutover /
rollback shape against the real `resolve_subscribe_loop_backend`
resolver (no shim — PR #181 has shipped the upstream resolver
since Tag-22) and emits a tri-state exit code that the operator
can wire into shell gates and PR checks.

## Subscribe-Loop-Lag-Stability (A6) and Cross-Modul-Drift (A7)

The Welle-6 smoke adds **two** Welle-6-specific asserts on top of
the Welle-1/2/3 shape (A1..A5 + R1), symmetric to Welle-4/5's
A6+A7:

* **A6 subscribe-loop-lag-stability (output-reply-timeliness):**
  the smoke captures a deterministic 12-sample synthetic lag-
  fixture (sub-millisecond lag-values that bracket the
  `persona_engine.subscribe.lag_seconds` histogram bucket spec)
  **BEFORE the cutover-step constructs the `PHASE_POST` env-map**.
  After the cutover (engine-reboot with
  `WAKIR_SUBSCRIBE_LOOP_BACKEND=rust`), the smoke re-emits the
  same lag-fixture via the Python authority a second time and
  asserts byte-equality of the JCS-canonical bytes of an ack-
  record built from the focus-component message-handling path.
  **Additionally**, the smoke verifies that the per-phase mean and
  P95 of the synthetic lag distribution stay within a 25% drift
  envelope across pre/post boots — the operator-Sicht
  output-reply-timeliness contract. Severity: **caution**. A
  hash mismatch or lag-distribution drift here signals subscribe-
  loop encoder drift OR ack-emission-rate drift between pre and
  post, which is a Tomás-Zone-K cross-modul drift signal, not a
  Pilot-VM-cutover blocker.

* **A7 cross-modul-drift-to-Welle-7 (subscribe_loop × recovery_workflow):**
  verifies that the `recovery` env-var stays at `python` in
  `PHASE_POST` and that the per-boot `recovery` BackendDecision
  `chosen_backend` field matches the env-var requested-value
  byte-for-byte in **every** phase. This is the cross-modul
  invariant: the subscribe_loop cutover MUST NOT silently force
  the recovery component into a different backend (the parallel-
  Welle joint-cutover concern). Severity: **blocker** — a fail
  here means subscribe_loop's resolver leaked into the recovery
  decision path, which would invalidate the parallel-Welle
  isolation contract.

A7 is **symmetric to Welle-7's A7**: Welle-7's A7 checks that
recovery's cutover does not leak into subscribe_loop; Welle-6's
A7 checks that subscribe_loop's cutover does not leak into
recovery. Together they pin the parallel-Welle isolation contract
bidirectionally — both smokes must report GREEN for the joint-
Welle cutover to be considered safe.

## FSM-Awareness pre-check

Per Auftrag-Tag-39, the subscribe_loop cutover must NOT be started
or stopped inside an FSM-cutover-window. FSM (Welle-5) was already
cutovert in KW-26; by KW-27 the FSM substrate is stable on Rust-
default. The smoke pins `WAKIR_FSM_BACKEND=rust` in every phase
to reflect the realistic post-KW-26 runtime posture. The
envelope's `fsm_post_cutover_state` field confirms FSM is in the
expected state.

## Substrate inventory

| Substrate | PR | Commit | Role |
|---|---|---|---|
| subscribe_loop Rust-Default-Resolver (ENV-gated) | [#181](https://github.com/wakir-labs/wakir-runtime/pull/181) | Tag-22 | The upstream `resolve_subscribe_loop_backend` the smoke calls directly. |
| subscribe_loop Cross-Lang Pins | [#172](https://github.com/wakir-labs/wakir-runtime/pull/172) | Tag-19 | Ack-record cross-lang fixture vectors A6 cross-checks. |
| recovery_workflow Rust-Default-Resolver | [#135](https://github.com/wakir-labs/wakir-runtime/pull/135) / [#167](https://github.com/wakir-labs/wakir-runtime/pull/167) | Tag-13 substrate / Tag-17 wiring | Welle-7 partner resolver (used in A7 cross-modul-drift check). |
| recovery_workflow Cross-Lang Pins | [#176](https://github.com/wakir-labs/wakir-runtime/pull/176) | Tag-20 | Welle-7 partner cross-lang fixture. |
| Welle-5 (FSM) Cutover-Smoke | [#249](https://github.com/wakir-labs/wakir-runtime/pull/249) | `3064077` | Pattern-parity sibling; Welle-6 mirrors the structural shape. |

## Resolver-provenance (subscribe_loop always upstream)

Welle-6 uses the **real upstream resolver**
`resolve_subscribe_loop_backend` directly. The resolver has been
in baseline since PR #181 (Tag-22). The smoke imports it via
`_import_resolver()` and never constructs a shim for the focus.
The `resolver_provenance` field in the envelope reports
`"upstream"` for `subscribe_loop` in every run.

## Asserts

| Assert | Severity | Description |
|---|---|---|
| **A1** `backend_flip` | blocker | post-cutover subscribe_loop `chosen_backend` == `rust` across all PHASE_POST boots. |
| **A2** `cross_lang_parity_hash` | blocker | structural-projection parity-hash identical between PHASE_POST and PHASE_ROLLBACK. |
| **A3** `latency_within_tolerance` | caution | post-cutover P95 latency <= pre-baseline P95 × (1 + tolerance%). Default 20% per ADR-0065 §AC-2. |
| **A4** `decision_count_in_place` | caution | total post-cutover decisions == `expected_components × boots_per_phase`. |
| **A5** `fallback_clean` | blocker | no `fallback_reason` populated on subscribe_loop PHASE_POST records. |
| **R1** `rollback_to_python` | blocker | rollback-phase subscribe_loop `chosen_backend` == `python`. |
| **A6** `subscribe_loop_lag_stability` | caution | Ack-record JCS bytes byte-stable across pre/post via Python authority AND lag-distribution mean+P95 within 25% drift envelope. |
| **A7** `cross_modul_drift_welle_7_recovery` | blocker | recovery `chosen_backend` == `python` across all PHASE_POST records (parallel-Welle isolation, symmetric to Welle-7 A7). |

Exit-code triad:

| Exit | Band | Meaning |
|---|---|---|
| `0` | GREEN | All asserts pass. Cutover proceeds. |
| `1` | CAUTION | At least one caution-severity assert failed. |
| `2` | ROLLBACK_RECOMMENDED | At least one blocker-severity assert failed. |

## Operator invocation

### GREEN-path (default)

```bash
python3 scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py \
    --output out/welle-6-smoke.json

# Or via bash wrapper:
bash scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh \
    --output out/welle-6-smoke.json
```

### Pre-PR-#241 baseline (10 components)

```bash
python3 scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py \
    --expected-components 10 \
    --output out/welle-6-smoke.json
```

### Higher boots for tighter percentile sample (CI hot-path)

```bash
python3 scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py \
    --boots-per-phase 12 \
    --latency-tolerance-pct 100 \
    --output out/welle-6-smoke.json
```

### Skip A6 (e.g. import-path-restricted CI)

```bash
python3 scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.py \
    --skip-lag-stability-parity \
    --output out/welle-6-smoke.json
```

A7 cross-modul-drift is independent of A6 and always runs.

## Decision matrix

| A1 | A2 | A5 | A7 | R1 | A3 | A4 | A6 | Exit | Operator-Action |
|---|---|---|---|---|---|---|---|---|---|
| pass | pass | pass | pass | pass | pass | pass | pass | **GREEN** | Proceed to live-smoke. |
| pass | pass | pass | pass | pass | **fail** | pass | pass | **CAUTION** | A3 latency: bump `--latency-tolerance-pct 100`. |
| pass | pass | pass | pass | pass | pass | pass | **fail** | **CAUTION** | A6 ack-record encoder drift OR lag distribution drift > 25%. Tomás-Zone-K signal. |
| **fail** | * | * | * | * | * | * | * | **ROLLBACK** | A1: post-cutover subscribe_loop is not rust. |
| * | * | * | **fail** | * | * | * | * | **ROLLBACK** | A7: **subscribe_loop cutover leaked into recovery path**. KW-27 Doppel-Welle isolation broken. Roll back subscribe_loop AND Welle-7. |

## Cross-Modul-Drift Mitigation to Welle-7 (symmetric A7)

The A7 assert is the **engineering substance** of the KW-27
Doppel-Welle mitigation, viewed from the Welle-6 side. The risk
scenario Tomás flagged is **"Welle-6's cutover machinery silently
changes Welle-7's behaviour"** — env-var clobber, boot-order
coupling, or shared cache could all leak subscribe_loop's "rust"
answer into recovery's decision path.

Welle-7 (`recovery_workflow`) runs its own smoke in parallel. The
Welle-7 smoke's A7 verifies subscribe_loop's stability under
recovery's cutover (the inverse leak direction). The two smokes
are independent (different focus-components, different env-vars)
but their joint passing is the operator-Sicht parallel-Welle
isolation contract.

## CI integration

The Welle-6 validation workflow (when wired) consumes the
existing acceptance steps plus the Cross-Modul-Stress-Test.
**This smoke is the local-hermetic precursor**, not a CI workflow
step. Operators wire it into pre-PR shell-gates via:

```bash
bash scripts/phase-3c/welle-6-subscribe-loop-cutover-smoke.sh \
    --output out/welle-6-smoke.json
```

GREEN -> proceed. CAUTION -> review the specific assert.
ROLLBACK -> do NOT proceed.

## Test reference

[`tests/phase_3c/test_welle_6_cutover_smoke.py`](../../tests/phase_3c/test_welle_6_cutover_smoke.py)
covers 17 hermetic scenarios. Run locally:

```bash
PYTHONPATH=. python3 -m pytest tests/phase_3c/test_welle_6_cutover_smoke.py -v
```

The test suite never imports the real wirelang package — every
test injects a stub `rust_backend_switch` module and a stub
`subscribe_ack` module via the `resolver_module=` /
`canonical_module=` kwargs.

## Henrik / Tomás Cross-Review checklist

Before merging the Welle-6 Pilot-VM cutover PR:

- [ ] A1..A5 + R1 + A6 + A7 all green on the local smoke (`out/welle-6-smoke.json` band=GREEN).
- [ ] Welle-7 smoke green in parallel (Henrik joint-verification — both A7 asserts must pass for the parallel-Welle contract to hold bidirectionally).
- [ ] `resolver_provenance.subscribe_loop` == `"upstream"` in the envelope.
- [ ] `cross_modul_drift_mitigation.recovery_chosen_backends_in_post_phase` == `["python"]`.
- [ ] `fsm_post_cutover_state.fsm_in_expected_post_kw26_state` == `true` (FSM cutovert from KW-26, stable on rust).
- [ ] `lag_stability.lag_sample_count` == 12 (deterministic fixture intact).
- [ ] Pilot-VM live-smoke confirms `WAKIR_SUBSCRIBE_LOOP_BACKEND=rust` flips successfully (binary deployed).
- [ ] Rollback-Drill <=10 min per ADR-0065 §Rollback-SLA.
- [ ] Tomás (Zone K) signed off on the joint Welle-6+7 substrate-readiness.
- [ ] Henrik signed off on the Cross-Modul-Drift-Mitigation evidence (A7 assert ran and passed in BOTH smokes).

## Operator-Hand vs. Mira-Hand split

| Step | Owner | Notes |
|---|---|---|
| Smoke run (this script) | Mira-Hand (CI / pre-PR) | Hermetic, runs on every Welle-6 PR. |
| `--expected-components` value selection | Mira-Hand | Default 11 (Tag-38 baseline). |
| `--latency-tolerance-pct` selection | Mira-Hand or Operator | Default 20% per ADR-0065 §AC-2. |
| Pilot-VM live-smoke | Operator-Hand | Real binary, real ENV-flip on Quadlet, real engine reboot. |
| Rollback (ENV-unset) | Operator-Hand | Smoke's R1 assert verifies the code-path. |
| A6 lag-distribution-drift investigation | Selin + Tomás (Zone K) | If A6 fires with a populated lag-distribution drift, off-smoke forensics required. |
| A7 cross-modul-drift investigation | Tomás (Zone K) + Henrik | If A7 fires, this is the smoke's only blocker that requires off-engine forensics. The Welle-7 A7 must be cross-checked in the same window. |

— Selin
