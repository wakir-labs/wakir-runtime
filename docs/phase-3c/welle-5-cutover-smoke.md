# Phase-3c Welle-5 Cutover-Smoke Runbook (`lifecycle_state_machine` / `fsm`)

| Field | Value |
|---|---|
| Owner | Selin Çelik (Persona-Engine), Tomás Reinhart (Matrix-Lead, Zone K), Henrik Voss (Caution-Owner) |
| ADRs | [0065](../../decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md), [0066](../../decisions/0066-phase-3c-doppel-cutover-acceleration-kw24.md) |
| Script (Python) | [`scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py`](../../scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py) |
| Script (Bash wrapper) | [`scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh`](../../scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh) |
| Tests | [`tests/phase_3c/test_welle_5_cutover_smoke.py`](../../tests/phase_3c/test_welle_5_cutover_smoke.py) (18 tests) |
| Sibling | [`docs/phase-3c/welle-4-cutover-smoke.md`](welle-4-cutover-smoke.md), [`docs/phase-3c/welle-3-cutover-smoke.md`](welle-3-cutover-smoke.md), [`docs/phase-3c/welle-2-cutover-smoke.md`](welle-2-cutover-smoke.md), [`docs/phase-3c/welle-1-cutover-smoke.md`](welle-1-cutover-smoke.md) |

## Purpose

This runbook describes the **End-to-End Cutover-Smoke** for ADR-0066
Welle-5 (`lifecycle_state_machine`, in-repo short form `fsm`,
BackendDecision-domain `fsm`), the **KW-26 Doppel-Welle** that runs
**in parallel with Welle-4** (`state_backing`).

Welle-5 is structurally the second-riskiest of the seven Phase-3c
waves because the focus-component (`fsm`) is the state-machine that
decides *which* transitions can be persisted at all (spec §3.3 —
six states, nine transitions). The Welle-4 partner (`state_backing`)
is the persistence trait that records `PersonaStateSnapshot`
envelopes via the `snapshot()` / `restore_latest()` /
`atomic_swap_pinned_offset()` API (spec §3.7.5). FSM transitions
write through state_backing: a transition takes the lock, mutates
in-memory state, then calls `state_backing.snapshot()` to persist
the new offset (engine.py L951 et seq.).

Tomás (Zone K) flagged the joint cutover as a
**Cross-Modul-Drift-Risk** during the ADR-0066 review: when both
modules flip from Python to Rust during the same KW-26 window, any
drift in their joint contract (FSM-transition byte-shape, accepted-
vs-rejected record ordering, transition-table membership) will
manifest as cross-modul state-corruption that no single-module
smoke can catch.

The smoke is **not** the Monday Live-Smoke (that one is Pilot-VM
operator-hand-territory). It is the local-hermetic precursor: it
exercises the full pre-cutover / cutover-step / post-cutover /
rollback shape against the real `resolve_fsm_backend` resolver (no
shim — PR #169 has shipped the upstream resolver since Tag-18) and
emits a tri-state exit code that the operator can wire into shell
gates and PR checks.

## FSM-Transition-Integrity (A6) and Cross-Modul-Drift (A7)

The Welle-5 smoke adds **two** Welle-5-specific asserts on top of
the Welle-1/2/3 shape (A1..A5 + R1), symmetric to Welle-4's A6+A7:

* **A6 fsm-transition-integrity (no phantom transitions):** the
  smoke captures a deterministic 6-transition `LifecycleTrace`
  (using the spec §3.3 happy-path: uninstantiated → spawning →
  running → despawning → uninstantiated → recovered → running)
  **BEFORE the cutover-step constructs the `PHASE_POST` env-map**.
  After the cutover (engine-reboot with `WAKIR_FSM_BACKEND=rust`),
  the smoke re-emits the same trace via the Python authority a
  second time and asserts byte-equality of the JCS-canonical bytes.
  **Additionally**, the smoke verifies that every accepted record
  in the recomputed trace points at a `(from_state, to_state)`
  edge that exists in `SPEC_VALID_TRANSITIONS` (the spec §3.3
  nine-edge closed enumeration) — no phantom transitions. This is
  the substrate-level oracle for the **FSM-Transition-Integrity
  property**: the JCS-canonical byte-shape of a `LifecycleTrace`
  written by the Python backend MUST be readable byte-for-byte by
  the Rust backend AND MUST only contain transitions from the
  spec's closed enumeration. The Rust pendant byte-parity is
  pinned at a separate substrate layer (the lifecycle-state-
  machine cross-lang fixture pins from PR #169 / PR #177). This
  smoke verifies the Python encoder is byte-stable across the
  pre/post window AND no phantom edges appear — the only oracle
  that does **not** require bringing up a real Rust binary in-
  process. Severity: **caution**. A hash mismatch or phantom-
  transition here signals Python FSM encoder drift, which is a
  Tomás-Zone-K cross-modul drift signal, not a Pilot-VM-cutover
  blocker.

* **A7 cross-modul-drift-to-Welle-4 (lifecycle_state_machine × state_backing):**
  verifies that the `state_backing` env-var stays at `python` in
  `PHASE_POST` and that the per-boot `state_backing` BackendDecision
  `chosen_backend` field matches the env-var requested-value
  byte-for-byte in **every** phase. This is the cross-modul
  invariant: the fsm cutover MUST NOT silently force the
  state_backing component into a different backend (the parallel-
  Welle joint-cutover concern). Severity: **blocker** — a fail
  here means fsm's resolver leaked into the state_backing decision
  path, which would invalidate the parallel-Welle isolation
  contract. The control-flow pin is what protects the substrate
  semantics from rot during the KW-26 Doppel-Welle window.

A7 is **symmetric to Welle-4's A7**: Welle-4's A7 checks that
state_backing's cutover does not leak into fsm; Welle-5's A7 checks
that fsm's cutover does not leak into state_backing. Together they
pin the parallel-Welle isolation contract bidirectionally — both
smokes must report GREEN for the joint-Welle cutover to be
considered safe.

The other five engine-emission-level asserts (A1..A5 + R1) mirror
the Welle-4 shape verbatim, re-pointed at `fsm` and
`WAKIR_FSM_BACKEND`. Note that `fsm` has only **two** backend enum
values (`python`, `rust`) — simpler than state_backing's three-
valued enum (`python`, `rust_inmemory`, `rust_natskv`).

## Substrate inventory

| Substrate | PR | Commit | Role |
|---|---|---|---|
| FSM Rust-Default-Resolver (ENV-gated) | [#169](https://github.com/wakir-labs/wakir-runtime/pull/169) | Tag-18 | The upstream `resolve_fsm_backend` the smoke calls directly (no shim). |
| FSM Cross-Lang Pins | [#177](https://github.com/wakir-labs/wakir-runtime/pull/177) | Tag-22 | LifecycleTrace cross-lang fixture vectors A6 cross-checks (Python JCS encoder byte-stability + transition-table integrity). |
| FSM Container-Image | [#226](https://github.com/wakir-labs/wakir-runtime/pull/226) | Tag-32 (Welle-4..7 bundle) | The Welle-5 Quadlet image (`wakir-persona-engine-fsm`). |
| BackendDecision #4 (fsm) | — | — | One of the eleven Tag-38 components in the engine-boot inventory. |
| federation_resolver wire-in | [#200](https://github.com/wakir-labs/wakir-runtime/pull/200) | `1ea7a60` | 9th BackendDecision. |
| bridge_audit_writer wire-in | [#212](https://github.com/wakir-labs/wakir-runtime/pull/212) | Tag-32 | 10th BackendDecision-slot. |
| bridge_audit_diff_engine wire-in (Reza-Tag-36 #241) | [#241](https://github.com/wakir-labs/wakir-runtime/pull/241) | Tag-36 | 11th BackendDecision-slot; landed pre-Tag-38. The smoke defaults to `--expected-components 11`. The shim path still works for pre-PR-#241 baselines. |
| Welle-4 Cutover-Smoke | [#245](https://github.com/wakir-labs/wakir-runtime/pull/245) | `0d8f5a6` | Pattern-parity sibling; Welle-5 smoke mirrors the Welle-4 shape verbatim, re-pointed at fsm with symmetric A6+A7. |

## Resolver-provenance (fsm always upstream)

Welle-5 uses the **real upstream resolver** `resolve_fsm_backend`
directly. The resolver has been in baseline since PR #169 (Tag-18).
The smoke imports it via `_import_resolver()` and never constructs
a shim for the focus. The `resolver_provenance` field in the
envelope reports `"upstream"` for `fsm` in every run.

The trailing 11th component (`bridge_audit_diff_engine`) may still
be served via the local shim path if the smoke is run against a
pre-PR-#241 baseline. The smoke handles both worlds via
`SHIM_COMPONENT_PRIMITIVES`: when an upstream resolver function is
missing, the shim wraps the existing env-var + bin-resolver
primitives to produce a BackendDecision with the same byte-shape
as the upstream resolvers. The `resolver_provenance` map surfaces
which surface the smoke exercised per component (`"upstream"` or
`"shim"`).

## Asserts

| Assert | Severity | Description |
|---|---|---|
| **A1** `backend_flip` | blocker | post-cutover fsm `chosen_backend` == `rust` across all PHASE_POST boots. |
| **A2** `cross_lang_parity_hash` | blocker | structural-projection parity-hash (drops `requested_backend`/`chosen_backend`) identical between PHASE_POST and PHASE_ROLLBACK. |
| **A3** `latency_within_tolerance` | caution | post-cutover P95 latency ≤ pre-baseline P95 × (1 + tolerance%). Default 20% per ADR-0065 §AC-2. |
| **A4** `decision_count_in_place` | caution | total post-cutover decisions == `expected_components × boots_per_phase`, and each per-boot slice has exactly `expected_components` records. |
| **A5** `fallback_clean` | blocker | no `fallback_reason` populated on fsm PHASE_POST records. |
| **R1** `rollback_to_python` | blocker | rollback-phase fsm `chosen_backend` == `python` across all PHASE_ROLLBACK boots. |
| **A6** `fsm_transition_integrity` | caution | LifecycleTrace JCS bytes byte-stable across pre/post via Python authority AND no phantom transitions (edges outside spec §3.3 `VALID_TRANSITIONS`). |
| **A7** `cross_modul_drift_welle_4_state_backing` | blocker | state_backing `chosen_backend` == `python` across all PHASE_POST records (parallel-Welle isolation, symmetric to Welle-4 A7). |

Exit-code triad:

| Exit | Band | Meaning |
|---|---|---|
| `0` | GREEN | All asserts pass (caution-skipped counts as pass). Cutover proceeds. |
| `1` | CAUTION | At least one caution-severity assert failed; cutover may proceed with Henrik / Tomás Cross-Review on the specific axis. |
| `2` | ROLLBACK_RECOMMENDED | At least one blocker-severity assert failed; operator MUST roll back before re-attempting. |

## Operator invocation

### GREEN-path (default)

```bash
# Default expected-components 11 (Tag-38 baseline 8ad125a,
# post-PR-#241 wire-in).
python3 scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py \
    --output out/welle-5-smoke.json

# Or via bash wrapper:
bash scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh \
    --output out/welle-5-smoke.json
```

### Pre-PR-#241 baseline (10 components)

```bash
# Running against a baseline that pre-dates the
# bridge_audit_diff_engine wire-in: pass --expected-components 10.
python3 scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py \
    --expected-components 10 \
    --output out/welle-5-smoke.json
```

### Higher boots for tighter percentile sample (CI hot-path)

```bash
# 12 boots per phase + 100% latency tolerance is the
# recommended CI invocation. The 1-microsecond pre-baseline
# observed on hot-path resolver runs (resolve_fsm_backend is a
# straight env-var dispatch + binary-probe call) yields a 20%
# tolerance of 0us under integer truncation, so the smoke
# routinely flags A3 CAUTION on raw default. Operators bumping
# to --latency-tolerance-pct 100 (still well within ADR-0065
# §AC-2 absolute regression headroom on the resolver hot-path,
# which has no functional latency budget on the order of
# microseconds) returns A3 GREEN.
python3 scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py \
    --boots-per-phase 12 \
    --latency-tolerance-pct 100 \
    --output out/welle-5-smoke.json
```

### Skip A6 (e.g. import-path-restricted CI)

```bash
python3 scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py \
    --skip-fsm-transition-parity \
    --output out/welle-5-smoke.json
```

Note that A7 cross-modul-drift is independent of A6 and always
runs (it consumes the engine BackendDecisions, not the canonical-
module surface).

### Tighter latency tolerance

```bash
python3 scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.py \
    --latency-tolerance-pct 10
```

## Decision matrix (interpret exit-code in context)

| A1 | A2 | A5 | A7 | R1 | A3 | A4 | A6 | Exit | Operator-Action |
|---|---|---|---|---|---|---|---|---|---|
| pass | pass | pass | pass | pass | pass | pass | pass | **GREEN** | Proceed to live-smoke (Mo Welle-5 day-0). |
| pass | pass | pass | pass | pass | **fail** | pass | pass | **CAUTION** | A3: latency regressed > 20%. Re-run with `--boots-per-phase 12 --latency-tolerance-pct 100` for a tighter percentile sample. If still failing under realistic tolerance: Henrik-Cross-Review on AC-2 carve-out. |
| pass | pass | pass | pass | pass | pass | **fail** | pass | **CAUTION** | A4: BackendDecision count drift. Verify `--expected-components` matches engine inventory (11 at Tag-38, 10 pre-PR-#241). Often signals a missing resolver wire-in (check resolver_provenance). |
| pass | pass | pass | pass | pass | pass | pass | **fail** | **CAUTION** | A6: Python LifecycleTrace encoder byte-shape drift OR phantom transition detected. Tomás-Zone-K signal — substrate-drift between pre/post window. NOT a Pilot-VM blocker but warrants investigation (check `phantom_transitions` field in the envelope first; an empty list means pure byte-drift, a populated list means an edge outside spec §3.3). |
| **fail** | * | * | * | * | * | * | * | **ROLLBACK** | A1: post-cutover fsm is not rust. Env-var or resolver wiring bug. |
| * | **fail** | * | * | * | * | * | * | **ROLLBACK** | A2: structural-projection drift. Resolver shape changed across phases. |
| * | * | **fail** | * | * | * | * | * | **ROLLBACK** | A5: fsm fell back to python on rust-request. Binary missing or probe failed. |
| * | * | * | **fail** | * | * | * | * | **ROLLBACK** | A7: **fsm cutover leaked into state_backing path**. KW-26 Doppel-Welle isolation broken. Roll back fsm AND Welle-4. |
| * | * | * | * | **fail** | * | * | * | **ROLLBACK** | R1: rollback phase still emits rust. ENV-unset path broken. |

## Cross-Modul-Drift Mitigation to Welle-4 (symmetric A7)

The A7 assert is the **engineering substance** of the KW-26
Doppel-Welle mitigation, viewed from the Welle-5 side. Why this
specific assert?

The risk scenario Tomás flagged is **not** "Welle-4 and Welle-5
have correlated failures" (that's monitoring's problem). The risk
is **"Welle-5's cutover machinery silently changes Welle-4's
behaviour"**. Specifically:

* **Env-var clobber:** if the fsm resolver writes to or reads from
  `WAKIR_STATE_BACKING_BACKEND` (e.g. via a shared "rust-mode"
  global flag), the state_backing BackendDecision would silently
  flip when fsm flips. A7 catches this because
  `WAKIR_STATE_BACKING_BACKEND` stays at `python` in the smoke's
  PHASE_POST env-map, but if the resolver leaks, state_backing's
  `chosen_backend` ≠ env-var-requested.
* **Boot-order coupling:** if fsm's Rust binary loads before
  state_backing's resolver runs and mutates some process-wide
  state (loaded shared lib, atexit handler, etc.), state_backing's
  resolver could see a different runtime than at baseline. A7
  catches the observable consequence: state_backing's
  `chosen_backend` in PHASE_POST.
* **Shared cache:** if both modules share a backend-resolution
  cache and fsm's cache entry overwrites state_backing's, the
  next state_backing.boot() reads fsm's "rust" answer for
  state_backing too. Again, A7 catches this via the env-var
  mismatch.

The A7 assert is **directly testable**: the test
`test_a7_cross_modul_drift_to_welle_4_state_backing_blocks_on_leak`
constructs a stub resolver that simulates the leak (state_backing
flips to rust whenever WAKIR_FSM_BACKEND is set to rust) and
asserts that A7 fires + the exit-code is ROLLBACK. The smoke
catches the substrate-level break, not just the symptom.

Welle-4 (`state_backing`) runs its own smoke in parallel. The
Welle-4 smoke's A7 verifies fsm's stability under state_backing's
cutover (the inverse leak direction). The two smokes are
independent (different focus-components, different env-vars) but
their joint passing is the **operator-Sicht** parallel-Welle
isolation contract.

## A6 Substrate-Level Test Coverage

The A6 assert combines two sub-axes that are tested independently:

* **Byte-stability:** the
  `test_a6_fsm_transition_integrity_caution_on_drift` test
  constructs a stub canonical module that salts its serialised
  output after the baseline-capture call, producing a hash
  mismatch in the recompute. A6 must fire with
  `match=False, phantom_transitions=[]`.
* **Phantom-transition trap:** the
  `test_a6_fsm_transition_integrity_caution_on_phantom_transition`
  test feeds the smoke a hand-crafted transition tuple with a
  `running → uninstantiated` edge (NOT in spec §3.3). A6 must
  fire with `match=True, phantom_transitions=[("running", "uninstantiated")]`.

Both sub-axes are caution-severity. The pairing pins the smoke's
A6 oracle: it detects encoder drift AND it detects spec-table
corruption, not just one or the other.

## CI integration

The Welle-5 validation workflow
(`.github/workflows/phase-3c-welle-5-validation.yml`) consumes the
existing five Mira-Hand-defined acceptance steps plus the
Cross-Modul-Stress-Test. **This smoke is the local-hermetic
precursor**, not a CI workflow step. Operators wire it into pre-PR
shell-gates via:

```bash
bash scripts/phase-3c/welle-5-lifecycle-state-machine-cutover-smoke.sh \
    --output out/welle-5-smoke.json
```

and feed the exit-code into the cutover-acceptance-decision
aggregator. GREEN → proceed to the validation workflow.
CAUTION → review the specific assert + decide whether to proceed.
ROLLBACK → do NOT proceed to the validation workflow.

## Test reference

[`tests/phase_3c/test_welle_5_cutover_smoke.py`](../../tests/phase_3c/test_welle_5_cutover_smoke.py)
covers 18 hermetic scenarios; the public-surface lock, the spec
§3.3 transition-table invariance, and the five exit-code paths
(GREEN / CAUTION-A3 / CAUTION-A6-drift / CAUTION-A6-phantom /
ROLLBACK-A1 / ROLLBACK-A5 / ROLLBACK-A7 / ROLLBACK-R1 / shim-path /
pre-PR-#241-baseline) are pinned. Run locally:

```bash
PYTHONPATH=. python3 -m pytest tests/phase_3c/test_welle_5_cutover_smoke.py -v
```

The test suite never imports the real wirelang package — every
test injects a stub `rust_backend_switch` module and a stub
`lifecycle_state_machine_canonical` module via the
`resolver_module=` / `canonical_module=` kwargs.

## Henrik / Tomás Cross-Review checklist

Before merging the Welle-5 Pilot-VM cutover PR:

- [ ] A1..A5 + R1 + A6 + A7 all green on the local smoke (`out/welle-5-smoke.json` band=GREEN).
- [ ] Welle-4 smoke green in parallel (Henrik joint-verification — both A7 asserts must pass for the parallel-Welle contract to hold bidirectionally).
- [ ] `resolver_provenance.fsm` == `"upstream"` in the envelope (PR #169 upstream resolver actually invoked).
- [ ] `cross_modul_drift_mitigation.state_backing_chosen_backends_in_post_phase` == `["python"]` (parallel-Welle isolation).
- [ ] `fsm_transition_integrity.spec_valid_transition_count` == 9 (spec §3.3 table is the expected nine-edge enumeration; deviation signals a smoke-vs-spec drift).
- [ ] `fsm_transition_integrity.baseline_phantom_transitions` == `[]` (the deterministic fixture only uses spec edges).
- [ ] Pilot-VM live-smoke confirms `WAKIR_FSM_BACKEND=rust` flips successfully (binary deployed, not a smoke-stub).
- [ ] Rollback-Drill ≤10 min per ADR-0065 §Rollback-SLA (Pilot-VM operator-hand-territory).
- [ ] Tomás (Zone K) signed off on the joint Welle-4+5 substrate-readiness.
- [ ] Henrik signed off on the Cross-Modul-Drift-Mitigation evidence (A7 assert ran and passed in BOTH smokes).

## Operator-Hand vs. Mira-Hand split

| Step | Owner | Notes |
|---|---|---|
| Smoke run (this script) | Mira-Hand (CI / pre-PR) | Hermetic, runs on every Welle-5 PR. |
| `--expected-components` value selection | Mira-Hand | Default 11 (Tag-38 baseline); pass 10 for pre-PR-#241 baselines. |
| `--latency-tolerance-pct` selection | Mira-Hand or Operator | Default 20% per ADR-0065 §AC-2. On the resolver hot-path (1us baseline), 20% truncates to 0us tolerance under integer division — operators routinely pass 100% to get a stable GREEN. The substance check is on absolute latency, not relative, at the resolver layer. |
| Pilot-VM live-smoke | Operator-Hand | Real binary, real ENV-flip on Quadlet, real engine reboot. The local smoke is the precursor, not the substitute. |
| Rollback (ENV-unset) | Operator-Hand | Smoke's R1 assert verifies the code-path; the live rollback is operator-driven. |
| A6 phantom-transition investigation | Selin + Tomás (Zone K) | If A6 fires with a populated `phantom_transitions` list, this signals a spec-table drift somewhere in the engine — off-smoke forensics required. |
| A7 cross-modul-drift investigation | Tomás (Zone K) + Henrik | If A7 fires, this is the smoke's only blocker that requires off-engine forensics. The Welle-4 A7 must be cross-checked in the same window. |

— Selin
