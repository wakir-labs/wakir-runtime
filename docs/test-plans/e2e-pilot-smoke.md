# Sprint-QA-Tag-15 — E2E-Pilot-Smoke-Suite Test-Plan

| Field | Value |
|---|---|
| Owner | Amara Osei (QA) |
| Date drafted | 2026-05-16 |
| Sprint | Sprint-QA-Tag-15 |
| Baseline-PR | wakir-runtime PR #42 (disposable-VM E2E-Acceptance-Gate) |
| Companion-PR | wakir-runtime PR #76 (CI-Live-VM-Acceptance-Wrapper) |
| Cross-Review | Tomas (Zone M, container-substrate), Selin (Zone M, persona-engine), Reza (Zone M, bridge-forward schema), Kai (Zone M, wrapper-test), Henrik (Zone N, quality-gate boundary) |

## 1. Goal

Extend the existing hermetic E2E-Acceptance-Gate harness so it
exercises the **Pilot-Phase-1b substance** as well as the
already-covered bootstrap/substrate-substance:

* Tomas-Persona-Container lifecycle invariants — the FSM walks the
  spec-canonical 6-state path on a real spawn → engineering-output →
  despawn cycle, and rejects every off-axis transition the
  spec marks invalid.
* V-907 build-time-pin + runtime-attest round-trip — the build-time
  pin computed against a frontmatter-only digest matches the
  pin the running container re-computes against the bind-mounted
  axis-A file.
* Doppelbetrieb-Bridge consistency — Pre-Framework-Tomás output and
  the wakir-Tomás container output land in the bridge-audit
  double-sink, the Doppelbetrieb-Score-CLI ingests both, and the
  four-axis verdict mapping is exhaustive and total over the
  documented score-space.
* Bug-42 symptom regression — the NATS-subscribe-loop in the
  async-real engine actually receives a published auftrag on the
  canonical subject and emits an output (this is the symptom
  Sprint-Pengine-12 Bug-41 fixed; we encode it as a
  regression-test so it cannot silently regress under future
  engine refactors).
* Bug-vector mapping for all seven `feedback_live_bringup_sandbox_gap`
  bug classes — the existing acceptance-gate CHECK_TO_BUGS map
  covers six smoke checks; we add explicit per-bug-class
  classification asserts so a future smoke-check rename does not
  silently drop a bug-class from the audit map.

## 2. Testability boundaries

This is a hermetic suite. It must not require:

* a live VM (the disposable-VM bring-up is Operator-Hand per
  ADR-0051 sandbox-disziplin);
* a live NATS server (we use an in-memory `asyncio.Queue`-backed
  fake msg-iterator, the same pattern the existing
  `test_nats_subscribe_loop` suite uses);
* network egress (we do not pull container images; we read the
  Quadlet source and persona-engine source to verify
  byte-level shape).

What this suite **does** run:

* Python in-process imports of the persona-engine FSM and V-907
  modules.
* `bash -n` syntactic checks of the wrapper and gate scripts.
* `subprocess.run` against the gate and wrapper with synthetic
  artefacts laid out in `tmp_path`.
* `jq` source-level shape checks against the wrapper's
  `emit_summary` block.

## 3. Test-Vector index

| TV-id | Subject under test | Source-of-truth |
|---|---|---|
| TV-PIL-FSM-01 | FSM has six states matching spec §3.3 | `lifecycle_state_machine.py` |
| TV-PIL-FSM-02 | FSM 9 valid transitions match spec §3.3 | `lifecycle_state_machine.py` |
| TV-PIL-FSM-03 | Full pilot lifecycle path `uninst → spawning → running → despawning → uninst` is walkable end-to-end and emits 4 transition-records in order | `LifecycleStateMachine` |
| TV-PIL-FSM-04 | Spec-canonical invalid transitions (`uninst → running`, `running → uninst`, `recovered → migrated`, ...) all raise `InvalidTransitionError` and leave state unchanged | `LifecycleStateMachine.transition_to` |
| TV-PIL-FSM-05 | Recovery path `uninst → recovered → running` is walkable (parity with Sprint-Pengine recovery-drill semantics) | `LifecycleStateMachine` |
| TV-PIL-FSM-06 | Engineering-output emission is FSM-state-gated: only `running` accepts an engineering-output event | source-level audit + state-machine semantics |
| TV-PIL-V907-01 | `compute_v907_pin` returns `sha256:<64-hex>` with stable byte-prefix length | `v907_verify.compute_v907_pin` |
| TV-PIL-V907-02 | Build-time pin computed at the source-tree axis-A matches the runtime-attest pin computed against the same bytes loaded from `/etc/wakir/persona/<slug>.md` (simulated via tmp-file copy) | `v907_verify.verify_v907_pin` |
| TV-PIL-V907-03 | Body-only mutations leave the pin invariant (spec §5: body out-of-hash) | `v907_verify.compute_v907_pin` |
| TV-PIL-V907-04 | Frontmatter mutations flip the pin (the build-time pin would *fail* runtime-attest if the on-disk axis-A drifts) — `verify_v907_pin` raises `PersonaHashDriftError` with the right `expected` / `observed` substrings | `v907_verify.verify_v907_pin` |
| TV-PIL-DOP-01 | Doppelbetrieb-Score `verdict()` is total over the four-quadrant input space (functional × byte-delta) | `wirelang.cli.doppelbetrieb_score.verdict` |
| TV-PIL-DOP-02 | Pre-Framework + wakir-Container outputs that are byte-identical produce `verdict == "pass"` with functional==1.0 and byte_delta==0 | `build_score` |
| TV-PIL-DOP-03 | Pre-Framework + wakir-Container outputs that diverge only in cosmetic whitespace stay above the spurious-divergence threshold and still `pass` | `build_score`, `spurious_divergence` |
| TV-PIL-DOP-04 | Score-schema contains the spec-canonical four axes (functional / byte-delta / structural / spurious) | `SCORE_SCHEMA` |
| TV-PIL-BUG42-01 | Subscribe-loop receives a published auftrag on `wakir.<env>.agent.agent.task.assigned.<slug>` via the fake-msg-iterator and emits an output on `task.output.<slug>` | `NatsSubscribeLoop.run_from_iterator` (or equivalent) |
| TV-PIL-BUG42-02 | The accepted inbound schema-id is exactly `wakir.agent.task-assigned/1` (regression: a schema-id drift would silently drop every auftrag) | `nats_subscribe_loop.ACCEPTED_INBOUND_SCHEMA` |
| TV-PIL-BUG42-03 | Malformed envelope (unknown schema-id) is dropped + emits a `task-input-malformed` audit-record (not silently dropped) | `NatsSubscribeLoop` |
| TV-PIL-BUG42-04 | `SUBSCRIBE_ENV_VAR` env-var is the documented async-path toggle (`WAKIR_SUBSCRIBE_ENV`) — a rename would silently revert to the sync path | `wirelang.persona_engine.cli` |
| TV-PIL-BUGMAP-01 | Bug-class-1 (resume-hint doubling) maps to the Bug-1 detector in `acceptance-gate.sh` | gate-source + memory |
| TV-PIL-BUGMAP-02 | Bug-class-2 (Volume-File-Names per-side substitution) is observable via the `quadlet-units-active` smoke-check failure-path (synthetic) | gate CHECK_TO_BUGS |
| TV-PIL-BUGMAP-03 | Bug-class-3 (Agent-Container Bundles-Volume `-federation-` middle missing) is observable via `spire-agent-healthy` or `spire-workload-api-reachable` failure-path | gate CHECK_TO_BUGS |
| TV-PIL-BUGMAP-04 | Bug-class-4 (Requires-Service-Name `-federation-` missing) is observable via `quadlet-units-active` failure-path | gate CHECK_TO_BUGS |
| TV-PIL-BUGMAP-05 | Bug-class-5 (bootstrap-phase non-idempotent) is observable via the Bug-1 detector path (idempotency is the resume-from contract) | gate-source |
| TV-PIL-BUGMAP-06 | Bug-class-6 (Bucket-Init `cryptography`-ModuleNotFound) is observable via `nats-jetstream-reachable` or `marker-stack-bucket-present` failure-path | gate CHECK_TO_BUGS |
| TV-PIL-BUGMAP-07 | Bug-class-7 (SPIRE-Server HCL-syntax error) is observable via `spire-server-healthy` failure-path | gate CHECK_TO_BUGS |
| TV-PIL-WRAP-01 | Wrapper `pull_script` heredoc is idempotent: clone-if-missing, fetch+reset-if-present; both branches present in source | wrapper-source |
| TV-PIL-WRAP-02 | Wrapper `reset_script` only targets `wakir-*` Quadlets, never wildcard-deletes `/etc/containers/systemd/*` | wrapper-source |
| TV-PIL-WRAP-03 | Wrapper exits **1** on SSH precheck fail (substrate problem), **2** on acceptance fail (on-VM script failure), **3** on wrapper-internal error (argv) — total exit-code contract | wrapper-source |
| TV-PIL-WRAP-04 | Wrapper invokes the on-VM acceptance script via `sudo` with the documented env-var prefix (`WAKIR_SIDE / PEER_SIDE / PEER_HOST / PILOT_MODE / SKIP_COSIGN_VERIFY`) — env-var rename here = silent acceptance-script env-misconfig | wrapper-source |
| TV-PIL-WRAP-05 | Wrapper `emit_summary` jq-call uses `--argjson acceptance_rc` (not `--arg`) so the rc lands in JSON as an integer (CI ingestion would silently swallow string-typed rc) | wrapper-source |

Goal: 20+ new hermetic vectors. The above lists 27 distinct
test-vectors (5 FSM, 4 V-907, 4 Doppelbetrieb, 4 Bug-42, 7 bug-class
mapping, 5 wrapper-coverage-audit add-ons). Some collapse into a
single parametrise; the implementation file enumerates each as a
separate pytest entry.

## 4. Cross-Review surface

* **Zone M — Tomas (Engineering Matrix-Lead):** TV-PIL-WRAP-01..05
  exercise Kai-owned wrapper-substance and Tomas-owned acceptance-
  script semantics. Tomas is the substrate-source-of-truth for the
  acceptance lane and reviews the wrapper-coverage-audit add-ons.
* **Zone M — Selin (Persona-Engine):** TV-PIL-FSM-01..06 +
  TV-PIL-V907-01..04 + TV-PIL-BUG42-01..04 exercise persona-engine
  semantics. Selin reviews the FSM-state-transition assert set and
  the subscribe-loop fake-iterator wiring.
* **Zone M — Reza (Wirelang):** TV-PIL-BUG42-02..03 + TV-PIL-DOP-04
  exercise schema-id constants and the Doppelbetrieb score-schema.
  Reza reviews schema-id constant pin.
* **Zone M — Kai (Container substrate):** TV-PIL-WRAP-01..05 are
  source-level audits of Kai's wrapper. Kai reviews.
* **Zone N — Henrik (Internal Audit):** the three Quality-Gate docs
  in `docs/quality-gates/` are the QA-side phase-gate criteria;
  Henrik reviews for ADR-consistency and audit-trail-coupling
  (which test-evidence items his quarterly audit-sample consumes
  vs. which are pure QA-evidence).

## 5. Reproducibility

All vectors run hermetically with:

```
pip install -e .
pytest tests/infra/test_pilot_phase_e2e_smoke.py \
       tests/infra/test_ci_live_vm_wrapper_coverage_audit.py
```

— Amara
