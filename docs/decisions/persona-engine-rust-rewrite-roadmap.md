# Persona-Engine Rust-Rewrite-Roadmap (Sprint-Pengine-13 Strategy Doc)

**Author:** Selin Çelik (Persona-Engine-Engineer)
**Date:** 2026-05-16
**Status:** Strategy proposal — NOT implementation
**Trigger:** ADR-0035 (`Sprache-pro-Komponente`) requires the Persona-
Engine in Rust for Phase-1b/2. The live Pilot 0.5.0-pilot container
runs Python (`wirelang/persona_engine/*.py`). This document inventories
the Python surface, proposes a Rust-crate mapping, sketches a phased
double-runtime bridge → cutover plan, and lists acceptance gates for
the Phase-2 Rust cutover.

This is a strategy proposal that requires ADR-level approval before
any implementation work begins. The Pilot-Phase remains on the Python
engine; this document defines what the Rust replacement looks like
when the Pilot-Phase concludes.

---

## 1 / Python-Engine Surface Inventory

### 1.1 Module-by-module surface (wirelang/persona_engine/)

| Module | Purpose | Python deps | Public surface |
|---|---|---|---|
| `__init__.py` | Package re-exports | — | `__version__`, `PersonaEngine`, `AsyncPersonaEngine`, `BridgeAuditWriter`, etc. |
| `engine.py` | Sync engine (boot/spawn/run/despawn) | stdlib + internal | `PersonaEngine`, `ENGINE_VERSION`, `resolve_env`, `EnvContract`, `EnvContractError` |
| `engine_async.py` | Async engine wrapper | `asyncio`, `signal`, internal | `AsyncPersonaEngine`, `ASYNC_ENGINE_VERSION`, `AsyncEngineTasks` |
| `cli.py` | CLI entry (`spawn`, `healthcheck`, `version`) | `argparse`, `os`, `asyncio` | `run_spawn`, exit-code constants, env-var resolvers |
| `lifecycle_state_machine.py` | FSM (uninstantiated → spawning → running → despawning → despawned) | stdlib | `LifecycleStateMachine`, `InvalidTransitionError`, state constants |
| `bridge_audit_writer.py` | Engineering-output double-sink (Bridge-Forward + state-backing) | `json`, internal | `BridgeAuditWriter`, `EngineeringOutputEvent` |
| `v907_verify.py` | V-907 persona-hash verify (axis-A → JCS → sha256 → match) | `rfc8785` (JCS), `hashlib`, `yaml` | `verify_v907_pin`, `PersonaHashComputeError`, `PersonaHashDriftError`, `V907VerifyResult` |
| `svid_workload_identity.py` | gRPC SPIFFE Workload-API client (probe + fetch) | `grpc.aio`, generated `_workload_api_pb2_minimal` | `probe_workload_api_socket`, `fetch_workload_svid`, `SvidProbeResult`, `SvidFetchResult`, `SvidFetchError`, `WorkloadApiClient` |
| `_workload_api_pb2_minimal.py` | Hand-rolled protobuf-stub for SPIFFE Workload-API (no protoc dep) | `grpc` | `WorkloadAPIStub`, `X509SVIDRequest`, `X509SVIDResponse` |
| `nats_subscribe_loop.py` | NATS subscribe-loop, envelope parse, output publish | `nats-py` (lazy), `json`, internal | `NatsSubscribeLoop`, `SubscribeLoopConfig`, mode constants, helpers |
| `state_backing.py` | Persona-State persistence (InMemory + NatsKV sync + async) | `nats-py.jetstream` (lazy), `json` | `PersonaStateBacking`, `PersonaStateBackingAsync`, `NatsKvPersonaStateBackingAsync`, `PersonaStateSnapshot`, `PersonaStateBackingError` |
| `llm_call_shim.py` | LLM-call abstraction (Phase-2 EchoReflectionLlmHook) | stdlib + internal | `LlmCallHook`, `LlmCallResult`, `EchoReflectionLlmHook`, `anthropic_messages_hook_phase_3_stub` |
| `recovery_workflow.py` | Recovery-drill orchestration | internal | `RecoveryWorkflow`, drill-step types |
| `drill_scheduler.py` | Periodic drill scheduler (background task) | `asyncio` | `DrillScheduler`, `DrillResult` |
| `despawn_clean.py` | Despawn-clean workflow (P1-P4 protocol) | internal | `DespawnCleanWorkflow` |
| `migrate_version.py` | State-pack version migration (ADR-0036 Self-Migration-Konverter) | `json` | `migrate_state_pack`, `KNOWN_ENGINE_VERSIONS`, `parse_semver`, `is_supported_engine_version` |

### 1.2 External wheel dependencies

| Wheel | Version pin | Purpose |
|---|---|---|
| `rfc8785` | `>=0.1.4` | JCS-canonical JSON for V-907 hash + envelope determinism |
| `PyYAML` | `>=6.0` | Persona-md axis-A YAML parsing |
| `shamir-mnemonic` | `>=0.3.0` | Shamir-Secret-Sharing for backup-substrate (Reza Zone-B) |
| `cryptography` | `>=42` | X.509 cert parsing for SVID (`not_after`, SAN URIs) |
| `nats-py` | `>=2.6` | NATS pub-sub + JetStream KV state-backing |
| `grpcio` | `>=1.60` | SPIFFE Workload-API gRPC channel |

### 1.3 Internal types crossing engine ↔ rest

- `EnvContract` (sync engine input)
- `V907VerifyResult` (boot output)
- `SvidProbeResult` + `SvidFetchResult` (SVID-fetch output)
- `PersonaStateSnapshot` (state-pack envelope; **byte-stable** across engines per migrate_version contract)
- `EngineeringOutputEvent` (Bridge-Audit-Writer emit type)
- `LlmCallResult` (LLM-hook return)

The state-pack envelope is the cross-engine determinism anchor — Rust
engine MUST produce byte-identical JCS for the same logical state, or
the Self-Migration-Konverter (ADR-0036) cannot bridge.

---

## 2 / Rust Crate Mapping

### 2.1 Module → crate map

| Python module | Rust crate(s) | Notes |
|---|---|---|
| `engine.py` + `engine_async.py` | `wakir-persona-engine-core` (new) | Tokio-async-first; sync wrapper around async core via `block_on` for backward-compat. |
| `cli.py` | `wakir-persona-engine-cli` (new, binary crate) | `clap` for argparse-parity. Same exit codes. |
| `lifecycle_state_machine.py` | inline in core crate, **type-state-pattern** | Selin's stärke per persona-def (Rust ownership = lifecycle modeling). `PhantomData<Uninstantiated>` → `PhantomData<Running>` etc. |
| `bridge_audit_writer.py` | inline in core crate | `serde_json` for emit; double-sink trait. |
| `v907_verify.py` | `serde-json-canonicalization` crate (rust crates.io) for JCS; `sha2` crate for sha256; `serde_yaml` for axis-A | `serde-json-canonicalization` v0.2+ implements RFC-8785. Byte-equiv with `rfc8785` Python wheel verified via test vectors. |
| `svid_workload_identity.py` | `tonic` for gRPC + auto-generated stub from `spiffe-workload-api.proto` | Tonic replaces the hand-rolled `_workload_api_pb2_minimal.py`. |
| `_workload_api_pb2_minimal.py` | auto-generated by `tonic-build` from `.proto` | Removed entirely. |
| `nats_subscribe_loop.py` | `async-nats` crate (Synadia-maintained) | Native Tokio NATS client. JetStream + core support both first-class. |
| `state_backing.py` | `async-nats::jetstream::kv` | JetStream KV is supported in async-nats >= 0.34. |
| `llm_call_shim.py` | trait + `reqwest` + `serde_json` for Phase-3 Anthropic | Phase-2 echo-hook trivially port. |
| `recovery_workflow.py` | inline in core crate | |
| `drill_scheduler.py` | `tokio::time::interval` + `tokio::task` | |
| `despawn_clean.py` | inline in core crate | |
| `migrate_version.py` | inline in core crate, `semver` crate | |

### 2.2 Wheel dependency → Rust crate mapping

| Python wheel | Rust crate | Status |
|---|---|---|
| `rfc8785` | `serde-json-canonicalization` v0.2+ | Available; byte-equiv test vectors needed |
| `PyYAML` | `serde_yaml` v0.9+ | Available; round-trip test vectors needed |
| `shamir-mnemonic` | `shamirsecretsharing` crate OR Reza-built crate | **Open question** — see §2.3 |
| `cryptography` | `rustls` + `x509-parser` OR `rustcrypto/x509-cert` | Available; cert-parse parity test vectors needed |
| `nats-py` | `async-nats` | Available; Synadia-maintained, parity-tested |
| `grpcio` | `tonic` | Available; Tokio-native |

### 2.3 Open crate questions

- **Shamir-Secret-Sharing.** The Python `shamir-mnemonic` wheel
  implements SLIP-0039 (Trezor's variant with mnemonic-encoded
  shares). Rust crates: `shamirsecretsharing` (Apache-2.0,
  generic-bytes; no SLIP-0039 mnemonic layer) vs.
  `slip-0039` (apparently not yet on crates.io; need verification).
  **Action:** Reza Zone-B + Zone-L cross-review before crate-pin —
  the backup-substrate format is identity-substrate-critical and a
  format-mismatch breaks recovery.
- **JCS determinism cross-language.** The Python `rfc8785` wheel
  and Rust `serde-json-canonicalization` must produce
  byte-identical output for **all** envelope shapes the engine
  emits. Test vectors needed for: floats (no engine uses floats —
  enforce strictly), Unicode-escape edge cases, key-ordering with
  numeric vs. alphabetic keys.
- **Persona-md YAML parse.** Python `yaml.safe_load` vs.
  `serde_yaml` may differ on edge cases (anchor-resolution, !!str
  vs. raw, etc.). Persona-md fixtures need to be canonicalised to
  YAML 1.2 strict before the Rust engine ships, or the V-907 hash
  drifts.

---

## 3 / Phased Roll-out Plan

### Phase 0 — Strategy approval (this document)

- Aufsichtsrat / CTO approval of this roadmap.
- ADR-0XXX (follow-up to ADR-0035) formalises the Rust-Persona-
  Engine crate split + cutover-gate criteria.
- Reza Zone-B + Zone-L cross-review on Shamir + cryptography
  crate-pins.
- Tomás Zone-K cross-review on JCS + V-907 hash byte-equiv test
  vectors.
- Estimated duration: 1-2 weeks calendar.

### Phase 1 — Doppelbetrieb-Bridge (Rust-Core skeleton, runs alongside Python)

**Goal:** Build the Rust core crate to feature-parity with the Python
engine, exercised in a side-by-side `Doppelbetrieb` mode where both
engines process the same NATS auftrags and a comparator validates
byte-equivalence of:

1. V-907 pin computation on the same axis-A fixture.
2. Engineering-output envelope JCS bytes for the same prompt.
3. State-pack envelope JCS bytes for the same lifecycle transitions.

**Deliverables:**

- `wakir-persona-engine-core` crate at v0.1.0 with all modules in
  §2.1 stubbed + unit-tested.
- A `wakir-persona-engine-shadow` binary that runs as a
  per-persona-slug sidecar in the Pilot, subscribes to the same
  `wakir.<env>.agent.agent.task.assigned.<slug>` subject, runs the
  echo-hook, and publishes to
  `wakir.<env>.agent.agent.task.output.<slug>-rust-shadow`. The
  Doppelbetrieb-Score-CLI gains a `--rust-shadow` flag that
  cross-compares Python + Rust outputs.
- Hermetic test surface: 200+ tests covering V-907, FSM,
  state-backing, subscribe-loop, despawn-clean.
- Estimated duration: 4-6 weeks (1.5 engineers).

### Phase 2 — Rust-crate-pro-Modul cutover (per-module flip)

**Goal:** Replace the Python module with the Rust crate one module
at a time, behind a feature flag. Module-flip order (lowest risk
first):

1. `v907_verify` — pure function, hermetic test vectors.
2. `lifecycle_state_machine` — type-state-pattern in Rust.
3. `bridge_audit_writer` — emit-side determinism.
4. `migrate_version` — pure function on state-pack envelopes.
5. `state_backing` (InMemory) — pure abstraction.
6. `nats_subscribe_loop` (core-callback mode only) — async-nats
   parity.
7. `state_backing` (NatsKV async) — JetStream KV parity.
8. `svid_workload_identity` — Tonic gRPC parity.
9. `recovery_workflow` + `drill_scheduler` — orchestration layer.
10. `engine` + `engine_async` + `despawn_clean` + `cli` — wraps it
    all up.

Each flip ships as a Quadlet-pinned image bump
(`0.5.x-pilot → 0.6.x-pilot → ...`). The doppelbetrieb-Shadow
container stays up across all flips to catch regressions.

Estimated duration: 8-12 weeks (1 engineer + Kai for Quadlet
rotations).

### Phase 3 — Final cutover (Python removed)

**Goal:** Remove `wirelang/persona_engine/*.py` from the image
build, keep only the Rust binary. The Python wheel
(`wirelang/persona_engine/`) becomes a deprecated thin compatibility
shim for downstream consumers (Aisha persona-tooling).

**Cutover gate (see §4):** All Phase-2 module-flips green, all
acceptance gates passed, AR-approval recorded.

Estimated duration: 2-3 weeks.

---

## 4 / Acceptance Gates for Phase-2 Rust Cutover

### 4.1 Cross-engine byte-equivalence gates

- **Gate G-1 / V-907 byte-equiv:** For the full axis-A corpus
  (every persona-md in `agents-workspaces/*`), Python `verify_v907_pin`
  and Rust V-907 produce **identical** pin strings. Failure: halt.
- **Gate G-2 / State-pack JCS byte-equiv:** For 1000 randomised
  state-pack snapshots, Python `state_backing.dumps_jcs` and Rust
  equivalent produce **identical** bytes. Failure: halt.
- **Gate G-3 / Bridge-output JCS byte-equiv:** For 1000 randomised
  task-output envelopes (auftrag_id × prompt × hook-output), Python
  `build_output_envelope` and Rust equivalent produce **identical**
  bytes. Failure: halt.

### 4.2 Functional parity gates

- **Gate G-4 / FSM transition parity:** Every (source-state,
  transition) pair the Python FSM accepts, the Rust FSM accepts;
  every pair Python rejects, Rust rejects. Failure: halt.
- **Gate G-5 / Subscribe-loop callback semantics:** Bug-42-style
  multi-message-burst test (50 messages, 10ms apart) confirms zero
  message loss on both engines under identical conditions.
- **Gate G-6 / Despawn-clean P1-P4 protocol parity:** The despawn
  audit-trail emitted by both engines matches byte-for-byte for
  the same lifecycle sequence.

### 4.3 Operational gates

- **Gate G-7 / Container-image size:** Rust image MUST be
  ≤ 50% the size of the Python image (the Pilot 0.5.0-pilot is
  ~250 MB; Rust target ≤ 125 MB). Static-linked binary + minimal
  base image.
- **Gate G-8 / Boot-time-latency:** Rust engine boot()→running
  transition completes in ≤ 50% the Python engine wall-time on
  the same Pilot-VM. Measured via `engineering-output
  spawn-init-complete` audit event timestamps.
- **Gate G-9 / Doppelbetrieb-Shadow 14-day-clean:** The
  Doppelbetrieb-Shadow runs alongside the Python engine for 14
  consecutive Pilot-days with **zero** byte-divergence on
  engineering-output envelopes. Cross-checked by the
  Doppelbetrieb-Aggregate-CLI weekly bilanz.

### 4.4 Governance gates

- **Gate G-10 / Reza Zone-B/L sign-off:** Identity-substrate +
  schema sign-off on the Rust crate choice (especially Shamir
  + cryptography).
- **Gate G-11 / Tomás Zone-K sign-off:** WAT-OTS + V-907
  sign-off on the Rust V-907 implementation.
- **Gate G-12 / Kai Zone-J sign-off:** Container substrate
  (Quadlet, supply-chain provenance) sign-off on the Rust
  image-build workflow.
- **Gate G-13 / Aisha HR Persona-Definition compatibility:**
  Persona-md axis-A files unchanged; YAML strict-mode parse
  identical in both engines on the full agents-workspaces corpus.
- **Gate G-14 / Henrik Audit sign-off:** Audit-trail emit shape
  unchanged; double-sink semantics preserved.
- **Gate G-15 / AR + CTO final approval:** Mira + Priya + AR
  sign-off recorded in an ADR-0XXX-cutover document.

---

## 5 / Open Risks

- **Doppelbetrieb-Shadow infrastructure cost.** Running two
  engines per persona doubles the container footprint during
  Phase-1/2. Pilot is single-persona (tomas) so the absolute cost
  is small; Phase-2 cluster expansion makes this more visible.
- **Self-Migration-Konverter regression.** ADR-0036 defines the
  state-pack format-migration contract. If the Rust engine emits
  a state-pack with even a single-byte JCS-difference, all stored
  snapshots become un-readable for the Rust engine without going
  through the migration konverter. Mitigation: G-2 gate, plus a
  one-shot bulk-migrate batch tool that operates on the live
  NatsKV bucket pre-cutover.
- **Rust ecosystem maturity.** `async-nats` is Synadia-maintained
  and battle-tested; `tonic` is mature; `serde-json-canonicalization`
  is younger. JCS-canonicalization edge cases are the highest-risk
  area for byte-divergence — extensive test vectors are
  non-negotiable.
- **Persona-Engine team capacity.** Phase-1 + Phase-2 is a
  4-6 month commitment for a single engineer; AR needs to weigh
  this against Pilot-feature-velocity.

---

## 6 / Out-of-Scope (explicitly)

- **Persona-Definition format changes.** This roadmap is engine-
  side; Aisha's persona-md governance is unchanged.
- **WAT-Core re-implementation.** Tomás's WAT crate is already
  Rust (Sprint-Tag-N-Wert-Hash); this roadmap does not touch it.
- **Identity-Substrate (Reza) re-implementation.** SPIRE +
  trust-bundle handling stays where it is; the engine only
  consumes SVIDs.
- **Container-Bridge (Kai) infra changes.** Quadlet rotation
  pattern unchanged; only the image tag/contents flip per Phase-2
  module-cutover.
- **Wirelang schema changes.** Reza Zone-B's schema-formalisation
  is independent of this roadmap.

---

## 7 / Next Steps (if approved)

1. Mira / Priya / AR review of this document (review-deadline:
   end of KW 22).
2. ADR-0XXX drafting (formal cutover decision record).
3. Tomás Zone-K + Reza Zone-B/L cross-review on crate choices.
4. Phase-0 close, Phase-1 sprint dispatch (Selin + Priya-CTO
   spawned Rust-engineer pairing).

---

*— Selin Çelik (Persona-Engine-Engineer), Sprint-Pengine-13*
