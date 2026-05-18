# Phase-3c Welle-4 Cutover-Smoke Runbook (`state_backing`)

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), Tomás Reinhart (Matrix-Lead, Zone K), Henrik Voss (Caution-Owner) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md), [0066](../../decisions/0066-phase-3c-doppel-cutover-acceleration-kw24.md) |
| Script (Python) | [`scripts/phase-3c/welle-4-state-backing-cutover-smoke.py`](../../scripts/phase-3c/welle-4-state-backing-cutover-smoke.py) |
| Script (Bash wrapper) | [`scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh`](../../scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh) |
| Tests | [`tests/phase_3c/test_welle_4_cutover_smoke.py`](../../tests/phase_3c/test_welle_4_cutover_smoke.py) (16 tests) |
| Sibling | [`docs/phase-3c/welle-3-cutover-smoke.md`](welle-3-cutover-smoke.md), [`docs/phase-3c/welle-2-cutover-smoke.md`](welle-2-cutover-smoke.md), [`docs/phase-3c/welle-1-cutover-smoke.md`](welle-1-cutover-smoke.md) |

## Purpose

This runbook describes the **End-to-End Cutover-Smoke** for ADR-0066
Welle-4 (`state_backing`), the **KW-26 Doppel-Welle** that runs **in
parallel with Welle-5** (`lifecycle_state_machine` / `fsm`).

Welle-4 is structurally the second-riskiest of the seven Phase-3c
waves because the focus-component (`state_backing`) is the
persistence trait that records `PersonaStateSnapshot` envelopes via
the `snapshot()` / `restore_latest()` /
`atomic_swap_pinned_offset()` API (spec §3.7.5). The Welle-5
partner (`fsm`) is the state-machine that decides *which*
transitions can be persisted at all (spec §3.3 — six states, nine
transitions). FSM transitions write through state_backing: a
transition takes the lock, mutates in-memory state, then calls
`state_backing.snapshot()` to persist the new offset (engine.py
L951 et seq.).

Tomás (Zone K) flagged the joint cutover as a
**Cross-Modul-Drift-Risk** during the ADR-0066 review: when both
modules flip from Python to Rust during the same KW-26 window, any
drift in their joint contract (snapshot byte-shape, offset
monotonicity, pinned-offset compare-and-swap semantics) will
manifest as cross-modul state-corruption that no single-module
smoke can catch.

The smoke is **not** the Monday Live-Smoke (that one is Pilot-VM
operator-hand-territory). It is the local-hermetic precursor: it
exercises the full pre-cutover / cutover-step / post-cutover /
rollback shape against the real `resolve_state_backing_backend`
resolver (no shim — PR #167 has shipped the upstream resolver
since Tag-17) and emits a tri-state exit code that the operator
can wire into shell gates and PR checks.

## Cross-Backend-Read-Compatibility (A6) and Cross-Modul-Drift (A7)

The Welle-4 smoke adds **two** Welle-4-specific asserts on top of
the Welle-1/2/3 shape (A1..A5 + R1):

* **A6 cross-backend-read-compatibility:** the smoke captures a
  deterministic `PersonaStateSnapshot` JCS-byte-blob via the
  Python authority's `snapshot_to_jcs_bytes()` **BEFORE the
  cutover-step constructs the `PHASE_POST` env-map**. After the
  cutover (engine-reboot with
  `WAKIR_STATE_BACKING_BACKEND=rust_inmemory`), the smoke re-emits
  the same snapshot via the Python authority a second time and
  asserts byte-equality. This is the substrate-level oracle for
  the **Cross-Backend-Read-Compatibility property**: the JCS-
  canonical byte-shape of a `PersonaStateSnapshot` written by the
  Python backend MUST be readable byte-for-byte by the Rust
  backend. The Rust pendant byte-parity is pinned at a separate
  substrate layer (the state_backing cross-lang fixture pins from
  PR #183, Tag-23). This smoke verifies that the Python encoder is
  byte-stable across the pre/post window — the only oracle that
  does **not** require bringing up a real Rust binary in-process.
  Severity: **caution**. A hash mismatch signals Python JCS
  encoder drift, which is a Tomás-Zone-K cross-modul drift signal,
  not a Pilot-VM-cutover blocker.

* **A7 cross-modul-drift-to-Welle-5 (state_backing × lifecycle_state_machine):**
  verifies that the `fsm` env-var stays at `python` in
  `PHASE_POST` and that the per-boot `fsm` BackendDecision
  `chosen_backend` field matches the env-var requested-value
  byte-for-byte in **every** phase. This is the cross-modul
  invariant: the state_backing cutover MUST NOT silently force the
  fsm component into a different backend (the parallel-Welle
  joint-cutover concern). Severity: **blocker** — a fail here
  means state_backing's resolver leaked into the fsm decision
  path, which would invalidate the parallel-Welle isolation
  contract. The control-flow pin is what protects the substrate
  semantics from rot during the KW-26 Doppel-Welle window.

The other five engine-emission-level asserts (A1..A5 + R1) mirror
the Welle-3 shape verbatim, re-pointed at `state_backing` and
`WAKIR_STATE_BACKING_BACKEND`. Note that `state_backing` has
**three** backend enum values (`python`, `rust_inmemory`,
`rust_natskv`); the smoke defaults to `rust_inmemory` per ADR-0066
§Welle-4. Operators can override via `--rust-backend-value
rust_natskv` if the KV cutover target is preferred.

## Substrate inventory

| Substrate | PR | Commit | Role |
|---|---|---|---|
| State-Backing Rust-Default-Resolver (ENV-gated) | [#167](https://github.com/wakir-labs/wakir-runtime/pull/167) | Tag-17 | The upstream `resolve_state_backing_backend` the smoke calls directly (no shim). |
| State-Backing Cross-Lang Pins | [#183](https://github.com/wakir-labs/wakir-runtime/pull/183) | Tag-23 | F1/F2/F3-equivalent fixture vectors A6 cross-checks (Python JCS encoder byte-stability). |
| State-Backing Container-Image | Phase-3a | — | The Welle-4 Quadlet image (`wakir-persona-engine-state-backing`). |
| BackendDecision #3 (state_backing) | — | — | One of nine baseline components in the 9-component inventory (Welle-1 §Substrate-inventory). |
| federation_resolver wire-in | [#200](https://github.com/wakir-labs/wakir-runtime/pull/200) | `1ea7a60` | 9th BackendDecision; the post-Welle-3-merge baseline default is 10 in-place components. |
| bridge_audit_writer container-image-pipeline | [#210](https://github.com/wakir-labs/wakir-runtime/pull/210) | `0168ac3` | 10th BackendDecision-slot; upstream resolver pending (Reza-Tag-36 wire-in target). |
| bridge_audit_diff_engine wire-in (Reza-Tag-36 #241) | pending | — | 11th BackendDecision-slot; once landed, operators flip `--expected-components 11`. The smoke transparently switches resolver-provenance for this slot from `"shim"` to `"upstream"`. |
| Welle-3 Cutover-Smoke | [#240](https://github.com/wakir-labs/wakir-runtime/pull/240) | `4803394` | Pattern-parity sibling; Welle-4 smoke mirrors the Welle-3 shape verbatim, re-pointed at state_backing. |

## Resolver-provenance (state_backing always upstream)

Unlike Welle-3 (which needed a resolver-shim for the focus-
component because `resolve_bridge_audit_writer_backend` was not
yet wired), Welle-4 uses the **real upstream resolver**
`resolve_state_backing_backend` directly. The resolver has been in
baseline since PR #167 (Tag-17). The smoke imports it via
`_import_resolver()` and never constructs a shim for the focus.
The `resolver_provenance` field in the envelope reports
`"upstream"` for `state_backing` in every run.

The trailing 10th and 11th components (`bridge_audit_writer` and
`bridge_audit_diff_engine`) may still be shim at the smoke's
default baseline `4803394` because the upstream resolver functions
for those are pending the Reza-Tag-36 and Reza-Tag-36-#241 wire-
ins. The smoke handles both worlds via
`SHIM_COMPONENT_PRIMITIVES`: when an upstream resolver function is
missing, the shim wraps the existing env-var + bin-resolver
primitives to produce a BackendDecision with the same byte-shape
as the upstream resolvers. The `resolver_provenance` map surfaces
which surface the smoke exercised per component (`"upstream"` or
`"shim"`).

## Asserts

| Assert | Severity | Description |
|---|---|---|
| **A1** `backend_flip` | blocker | post-cutover state_backing `chosen_backend` ∈ {`rust_inmemory`, `rust_natskv`} across all PHASE_POST boots. |
| **A2** `cross_lang_parity_hash` | blocker | structural-projection parity-hash (drops `requested_backend`/`chosen_backend`) identical between PHASE_POST and PHASE_ROLLBACK. |
| **A3** `latency_within_tolerance` | caution | post-cutover P95 latency ≤ pre-baseline P95 × (1 + tolerance%). Default 20% per ADR-0065 §AC-2. |
| **A4** `decision_count_in_place` | caution | total post-cutover decisions == `expected_components × boots_per_phase`, and each per-boot slice has exactly `expected_components` records. |
| **A5** `fallback_clean` | blocker | no `fallback_reason` populated on state_backing PHASE_POST records. |
| **R1** `rollback_to_python` | blocker | rollback-phase state_backing `chosen_backend` == `python` across all PHASE_ROLLBACK boots. |
| **A6** `cross_backend_read_compatibility` | caution | state-snapshot JCS bytes byte-stable across pre/post via Python authority. |
| **A7** `cross_modul_drift_welle_5_fsm` | blocker | fsm `chosen_backend` == `python` across all PHASE_POST records (parallel-Welle isolation). |

Exit-code triad:

| Exit | Band | Meaning |
|---|---|---|
| `0` | GREEN | All asserts pass (caution-skipped counts as pass). Cutover proceeds. |
| `1` | CAUTION | At least one caution-severity assert failed; cutover may proceed with Henrik / Tomás Cross-Review on the specific axis. |
| `2` | ROLLBACK_RECOMMENDED | At least one blocker-severity assert failed; operator MUST roll back before re-attempting. |

## Operator invocation

### GREEN-path (default)

```bash
# Default expected-components 10 (post-Welle-3-merge baseline,
# pre-Reza-Tag-36-#241 wire-in). Default rust target: rust_inmemory.
python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \
    --output out/welle-4-smoke.json

# Or via bash wrapper:
bash scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh \
    --output out/welle-4-smoke.json
```

### Post-Reza-Tag-36-#241-wire-in invocation

```bash
# Once the bridge_audit_diff_engine upstream resolver lands, bump
# expected-components to 11 so A4 tracks the full inventory.
python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \
    --expected-components 11 \
    --output out/welle-4-smoke.json
```

### Target rust_natskv instead of rust_inmemory

```bash
python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \
    --rust-backend-value rust_natskv \
    --output out/welle-4-smoke.json
```

### Skip A6 (e.g. import-path-restricted CI)

```bash
python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \
    --skip-state-snapshot-parity \
    --output out/welle-4-smoke.json
```

Note that A7 cross-modul-drift is independent of A6 and always
runs (it consumes the engine BackendDecisions, not the state-
backing module surface).

### Tighter latency tolerance

```bash
python3 scripts/phase-3c/welle-4-state-backing-cutover-smoke.py \
    --latency-tolerance-pct 10
```

## Decision matrix (interpret exit-code in context)

| A1 | A2 | A5 | A7 | R1 | A3 | A4 | A6 | Exit | Operator-Action |
|---|---|---|---|---|---|---|---|---|---|
| pass | pass | pass | pass | pass | pass | pass | pass | **GREEN** | Proceed to live-smoke (Mo Welle-4 day-0). |
| pass | pass | pass | pass | pass | **fail** | pass | pass | **CAUTION** | A3: latency regressed > 20%. Re-run with `--boots-per-phase 12` to get tighter percentile sample. If still failing: Henrik-Cross-Review on AC-2 carve-out. |
| pass | pass | pass | pass | pass | pass | **fail** | pass | **CAUTION** | A4: BackendDecision count drift. Verify `--expected-components` matches engine inventory. Often signals a missing resolver wire-in (check resolver_provenance). |
| pass | pass | pass | pass | pass | pass | pass | **fail** | **CAUTION** | A6: Python JCS encoder byte-shape drift. Tomás-Zone-K signal — substrate-drift between pre/post window. NOT a Pilot-VM blocker but warrants investigation. |
| **fail** | * | * | * | * | * | * | * | **ROLLBACK** | A1: post-cutover state_backing is not rust. Env-var or resolver wiring bug. |
| * | **fail** | * | * | * | * | * | * | **ROLLBACK** | A2: structural-projection drift. Resolver shape changed across phases. |
| * | * | **fail** | * | * | * | * | * | **ROLLBACK** | A5: state_backing fell back to python on rust-request. Binary missing or probe failed. |
| * | * | * | **fail** | * | * | * | * | **ROLLBACK** | A7: **state_backing cutover leaked into fsm path**. KW-26 Doppel-Welle isolation broken. Roll back state_backing AND Welle-5. |
| * | * | * | * | **fail** | * | * | * | **ROLLBACK** | R1: rollback phase still emits rust. ENV-unset path broken. |

## Cross-Modul-Drift Mitigation to Welle-5

The A7 assert is the **engineering substance** of the KW-26
Doppel-Welle mitigation. Why this specific assert?

The risk scenario Tomás flagged is **not** "Welle-4 and Welle-5
have correlated failures" (that's monitoring's problem). The risk
is **"Welle-4's cutover machinery silently changes Welle-5's
behaviour"**. Specifically:

* **Env-var clobber:** if the state_backing resolver writes to or
  reads from `WAKIR_FSM_BACKEND` (e.g. via a shared "rust-mode"
  global flag), the fsm BackendDecision would silently flip when
  state_backing flips. A7 catches this because `WAKIR_FSM_BACKEND`
  stays at `python` in the smoke's PHASE_POST env-map, but if the
  resolver leaks, fsm's `chosen_backend` ≠ env-var-requested.
* **Boot-order coupling:** if state_backing's Rust binary loads
  before fsm's resolver runs and mutates some process-wide state
  (loaded shared lib, atexit handler, etc.), fsm's resolver could
  see a different runtime than at baseline. A7 catches the
  observable consequence: fsm's `chosen_backend` in PHASE_POST.
* **Shared cache:** if both modules share a backend-resolution
  cache and state_backing's cache entry overwrites fsm's, the
  next fsm.boot() reads state_backing's "rust" answer for fsm too.
  Again, A7 catches this via the env-var mismatch.

The A7 assert is **directly testable**: the test
`test_a7_cross_modul_drift_to_welle_5_fsm_blocks_on_fsm_leak`
constructs a stub resolver that simulates the leak (fsm flips to
rust whenever the state_backing env-var is set to a rust value)
and asserts that A7 fires + the exit-code is ROLLBACK. The smoke
catches the substrate-level break, not just the symptom.

Welle-5 (`lifecycle_state_machine` / `fsm`) will run its own
smoke in parallel. The Welle-5 smoke's symmetrical A7 should
verify state_backing's stability under fsm's cutover. The two
smokes are independent (different focus-components, different
env-vars) but their joint passing is the **operator-Sicht**
parallel-Welle isolation contract.

## CI integration

The Welle-4 validation workflow
(`.github/workflows/phase-3c-welle-4-validation.yml`, PR #167
substrate-validation lineage) consumes this smoke as one of the
five Mira-Hand-defined acceptance steps. The workflow's Step-N
calls:

```bash
bash scripts/phase-3c/welle-4-state-backing-cutover-smoke.sh \
    --output ${RUNNER_TEMP}/welle-4-smoke.json
```

and feeds the exit-code into the cutover-acceptance-decision
aggregator. GREEN → all five steps pass → workflow uploads
`cutover-acceptance-decision-welle-4.json` artifact. CAUTION or
ROLLBACK → workflow fails the job and the artifact carries the
exact assert that fired.

## Test reference

[`tests/phase_3c/test_welle_4_cutover_smoke.py`](../../tests/phase_3c/test_welle_4_cutover_smoke.py)
covers 16 hermetic scenarios; the public-surface lock and the
five exit-code paths (GREEN / CAUTION-A3 / CAUTION-A6 / ROLLBACK-
A1 / ROLLBACK-A5 / ROLLBACK-A7 / ROLLBACK-R1) are pinned. Run
locally:

```bash
PYTHONPATH=. python3 -m pytest tests/phase_3c/test_welle_4_cutover_smoke.py -v
```

The test suite never imports the real wirelang package — every
test injects a stub `rust_backend_switch` module and a stub
`state_backing` module via the `resolver_module=` /
`state_backing_module=` kwargs.

## Henrik / Tomás Cross-Review checklist

Before merging the Welle-4 Pilot-VM cutover PR:

- [ ] A1..A5 + R1 + A6 + A7 all green on the local smoke (`out/welle-4-smoke.json` band=GREEN).
- [ ] Welle-5 smoke green in parallel (Henrik joint-verification).
- [ ] `resolver_provenance.state_backing` == `"upstream"` in the envelope (PR #167 upstream resolver actually invoked).
- [ ] `cross_modul_drift_mitigation.fsm_chosen_backends_in_post_phase` == `["python"]` (parallel-Welle isolation).
- [ ] Pilot-VM live-smoke confirms `WAKIR_STATE_BACKING_BACKEND=rust_inmemory` flips successfully (binary deployed, not a smoke-stub).
- [ ] Rollback-Drill ≤10 min per ADR-0065 §Rollback-SLA (Pilot-VM operator-hand-territory).
- [ ] Tomás (Zone K) signed off on the joint Welle-4+5 substrate-readiness.
- [ ] Henrik signed off on the Cross-Modul-Drift-Mitigation evidence (A7 assert ran and passed).

## Operator-Hand vs. Mira-Hand split

| Step | Owner | Notes |
|---|---|---|
| Smoke run (this script) | Mira-Hand (CI / pre-PR) | Hermetic, runs on every Welle-4 PR. |
| `--expected-components` value selection | Mira-Hand | Default 10; bump to 11 when Reza Tag-36 #241 lands. |
| `--rust-backend-value` selection | Mira-Hand or Operator | Default `rust_inmemory` is the ADR-0066 §Welle-4 cutover target. `rust_natskv` is the post-pilot follow-up. |
| Pilot-VM live-smoke | Operator-Hand | Real binary, real ENV-flip on Quadlet, real engine reboot. The local smoke is the precursor, not the substitute. |
| Rollback (ENV-unset) | Operator-Hand | Smoke's R1 assert verifies the code-path; the live rollback is operator-driven. |
| A7 cross-modul-drift investigation | Tomás (Zone K) + Henrik | If A7 fires, this is the smoke's only blocker that requires off-engine forensics. |

— Selin
