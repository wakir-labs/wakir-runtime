<!--
SPDX-License-Identifier: BUSL-1.1
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Business Source License 1.1; see ./LICENSE-BSL.md.
Change Date: 2030-05-15. Change License: Apache License 2.0.
-->

# Wakir Persona-Engine — Manifest 0.5.0-pre-cutover

**Tag-45 (2026-05-18). Engine-Konsolidierung vor Phase-3a/3b Doppelbetrieb-Cutover.**

This manifest is the single source of truth for the
0.5.0-pre-cutover engine release: which BackendDecision records the
boot path emits, which ENV flags gate each backend, which
cross-language pin-pack vectors anchor the Rust ↔ Python parity
substrates, and which sequence the engine follows from
`engine.__init__` to the first BackendDecision audit emission.

The manifest is intentionally **machine-readable** for the
hermetic Tag-45 integrity tests (see
`wirelang/tests/persona_engine/test_manifest_0_5_0_pre_cutover.py`)
and the cross-substrate parity gate
(`.github/workflows/cross-substrate-parity-gate.yml`).

> **Scope discipline (ADR-0036 / ADR-0043 / ADR-0065)** — this file
> documents the engine wiring. It does **not** modify persona
> definitions (Aisha-Domäne), WAT-core logic (Tomás-Domäne),
> identity-substrate design (Reza-Domäne), or container-infra
> beyond the Containerfile version bump (Kai-Domäne).

---

## 1. Component Inventory (9 BackendDecision Records, Boot-Ordered)

The 0.5.0-pre-cutover engine emits **exactly nine** `BackendDecision`
records per cold-start, in the order below. Each record names one
backend module that the engine resolves via
`wirelang.persona_engine.rust_backend_switch.resolve_*`. The 10th
component — `bridge-audit-writer` — is **enum-defined but not yet
wired into the boot sequence** (held back for Tag-46/47; see
§5 Backward-Compatibility).

| # | Component | Python Authority | Rust Pendant (Crate) | Cross-Lang Fixtures |
|---|---|---|---|---|
| 1 | recovery-workflow | `wirelang.persona_engine.recovery_workflow` | `persona-engine-recovery` | `tests/fixtures/recovery-workflow-cross-lang/fixtures.json` |
| 2 | state-backing | `wirelang.persona_engine.state_backing` | `persona-engine-state-backing` | `tests/fixtures/state-backing-cross-lang/fixtures.json` |
| 3 | lifecycle-fsm | `wirelang.persona_engine.lifecycle_state_machine` | `persona-engine-fsm` | `tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json` |
| 4 | v907-verify | `wirelang.persona_engine.v907_verify` | `persona-engine-v907-verify` | `tests/fixtures/v907-verify-cross-lang/fixtures.json` |
| 5 | bridge-diff | `wirelang.persona_engine.bridge_audit_diff_engine` | `persona-engine-bridge-diff` | `tests/fixtures/bridge-audit-diff-engine-cross-lang/fixtures.json` |
| 6 | subscribe-loop | `wirelang.persona_engine.subscribe_ack` | `persona-engine-subscribe-loop` | `tests/fixtures/subscribe-loop-cross-lang/fixtures.json` |
| 7 | anchor-emitter | `wirelang.persona_engine.anchor_emitter` | `persona-engine-anchor-emitter` | `tests/fixtures/anchor-emitter-cross-lang/fixtures.json` |
| 8 | svid-workload-identity | `wirelang.persona_engine.svid_workload_identity` | `persona-engine-svid-workload-identity` | `tests/fixtures/svid-workload-cross-lang/fixtures.json` |
| 9 | federation-resolver | `wirelang.identity.federation_resolver_canonical` | `persona-engine-federation-resolver` | `tests/fixtures/federation-resolver-cross-lang/fixtures.json` |

V-907 (record #4) is the **most critical** integrity anchor: any
byte-drift between Python authority and Rust pendant would silently
corrupt the WAT-audit substrate. The bridge-diff oracle (record #5)
is the Phase-3a Doppelbetrieb comparison gate.

---

## 2. ENV-Flag Schema (Consistent `WAKIR_*_BACKEND` Naming)

Every BackendDecision is gated by **two** ENV flags following the
identical convention: a backend selector (`python` / `rust` /
`canonical`, default `python`) and a Rust-binary path override. A
third optional knob (`WAKIR_RUST_BACKEND_TIMEOUT_S`) caps the
subprocess wait across **all** Rust backends.

### 2.1 Backend Selector ENVs (9 flags, one per component)

| Component | Selector ENV | Accepted Values | Default |
|---|---|---|---|
| recovery-workflow | `WAKIR_RECOVERY_BACKEND` | `python`, `rust` | `python` |
| state-backing | `WAKIR_STATE_BACKING_BACKEND` | `python`, `rust` | `python` |
| lifecycle-fsm | `WAKIR_FSM_BACKEND` | `python`, `rust` | `python` |
| v907-verify | `WAKIR_V907_VERIFY_BACKEND` | `python`, `rust` | `python` |
| bridge-diff | `WAKIR_BRIDGE_DIFF_BACKEND` | `python`, `rust` | `python` |
| subscribe-loop | `WAKIR_SUBSCRIBE_LOOP_BACKEND` | `python`, `rust` | `python` |
| anchor-emitter | `WAKIR_ANCHOR_EMITTER_BACKEND` | `python`, `rust` | `python` |
| svid-workload-identity | `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND` | `python`, `rust` | `python` |
| federation-resolver | `WAKIR_FEDERATION_RESOLVER_BACKEND` | `python`, `rust`, `canonical` | `python` |

### 2.2 Rust-Binary Path Override ENVs (9 flags, one per component)

| Component | Binary Path ENV |
|---|---|
| recovery-workflow | `WAKIR_RUST_RECOVERY_BIN` |
| state-backing | `WAKIR_RUST_STATE_BACKING_BIN` |
| lifecycle-fsm | `WAKIR_RUST_FSM_BIN` |
| v907-verify | `WAKIR_RUST_V907_VERIFY_BIN` |
| bridge-diff | `WAKIR_RUST_BRIDGE_DIFF_BIN` |
| subscribe-loop | `WAKIR_RUST_SUBSCRIBE_LOOP_BIN` |
| anchor-emitter | `WAKIR_RUST_ANCHOR_EMITTER_BIN` |
| svid-workload-identity | `WAKIR_RUST_SVID_WORKLOAD_IDENTITY_BIN` |
| federation-resolver | `WAKIR_RUST_FEDERATION_RESOLVER_BIN` |

### 2.3 Cross-Backend Timeout

`WAKIR_RUST_BACKEND_TIMEOUT_S` — integer seconds, default `30`,
applied uniformly to every Rust subprocess invocation. Operators
flip a single knob for slow CI lanes.

### 2.4 Validation Rules

- Unknown selector values raise `BackendSwitchValidationError` at
  resolution time (no silent fallback). Empty string ≡ unset ≡
  default.
- Selector values are **case-sensitive** lowercase. `Rust` /
  `RUST` are rejected.
- The Rust-binary path ENV is consulted **only** when the selector
  resolves to `rust`. A `rust` selector with no binary path falls
  back to the PATH lookup (`persona-engine-<component>` literal).

### 2.5 Held-Back ENV (Not Yet Wired Into Boot)

`WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` is defined for the future
10th-record extension but is not consulted during 0.5.0-pre-cutover
boot. The enum (`BridgeAuditWriterBackend`) and the resolver are
present in `rust_backend_switch.py` so that the wire-in is a single
engine.py change in Tag-46/47.

---

## 3. Cross-Language Pin-Pack Map (15 Phase-3a Crates @ 0.1.0)

The Tag-45 pre-cutover engine pins **all fifteen** Phase-3a Rust
crates at version `0.1.0`. The pin pack lives at
`infra/persona-engine/pin-pack-0.5.0-pre-cutover.yaml` and is the
machine-readable counterpart to the table below.

| # | Rust Crate (`wirelang-rust/crates/`) | Version | Cross-Lang Anchor |
|---|---|---|---|
| 1 | `persona-engine-recovery` | 0.1.0 | record #1 |
| 2 | `persona-engine-state-backing` | 0.1.0 | record #2 |
| 3 | `persona-engine-fsm` | 0.1.0 | record #3 |
| 4 | `persona-engine-v907-verify` | 0.1.0 | record #4 |
| 5 | `persona-engine-bridge-diff` | 0.1.0 | record #5 |
| 6 | `persona-engine-subscribe-loop` | 0.1.0 | record #6 |
| 7 | `persona-engine-anchor-emitter` | 0.1.0 | record #7 |
| 8 | `persona-engine-svid-workload-identity` | 0.1.0 | record #8 |
| 9 | `persona-engine-federation-resolver` | 0.1.0 | record #9 |
| 10 | `persona-engine-bridge-audit-writer` | 0.1.0 | held back (§5) |
| 11 | `persona-engine-bridge-audit-replay` | 0.1.0 | replay-side oracle |
| 12 | `persona-engine-anchor-submit-worker` | 0.1.0 | WAT-spool sibling |
| 13 | `persona-engine-frontmatter-parser` | 0.1.0 | Tag-34 parser substrate |
| 14 | `persona-engine-bridge-forward` | 0.1.0 | Python ↔ Rust forward pipe |
| 15 | `persona-engine-federation-frame-parser` | 0.1.0 | federation-frame oracle |

Records #1–9 are wired into the boot sequence and emit a
`BackendDecision` per cold-start. Records #10–15 are byte-parity
substrates that ship in 0.5.0-pre-cutover for cross-substrate
validation (cross-substrate-parity-gate workflow) but are consumed
only when explicitly invoked from the Python authority side.

---

## 4. Boot-Sequence Diagram

The engine `__init__` resolves the nine backends in a fixed,
deterministic order. Re-ordering would invalidate the
boot-fingerprint that the Doppelbetrieb oracle hashes for the
Phase-3a parity gate; any change here is an ADR-level decision.

```
PersonaEngine.__init__()
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  Stage 1 — synchronous resolver fan-out (no I/O)          │
│                                                            │
│  1. resolve_recovery_backend()         → emit decision #1 │
│  2. resolve_state_backing_backend()    → emit decision #2 │
│  3. resolve_fsm_backend()              → emit decision #3 │
│  4. resolve_v907_verify_backend()      → emit decision #4 │
│  5. resolve_bridge_diff_backend()      → emit decision #5 │
│  6. resolve_subscribe_loop_backend()   → emit decision #6 │
│  7. resolve_anchor_emitter_backend()   → emit decision #7 │
│  8. resolve_svid_workload_identity_…() → emit decision #8 │
│  9. resolve_federation_resolver_…()    → emit decision #9 │
└───────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  Stage 2 — substrate wiring (uses Stage-1 backends)       │
│                                                            │
│  • build_state_backing(...)                                │
│  • build_recovery_workflow(...)                            │
│  • build_v907_verifier(...)                                │
│  • build_bridge_diff(...)                                  │
│  • build_subscribe_ack_writer(...)                         │
│  • build_anchor_emitter(...)                               │
│  • build_svid_workload_resolver(...)                       │
│  • build_federation_resolver(...)                          │
└───────────────────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────────────────┐
│  Stage 3 — async runtime (NATS subscribe-loop, SVID-      │
│            refetch, JetStream-pull-mode toggle)            │
└───────────────────────────────────────────────────────────┘
        │
        ▼
   Engine ready for spawn (`.spawn(auftrag, ...)`).
```

**Invariants** (verified by hermetic tests in
`test_manifest_0_5_0_pre_cutover.py`):

- Stage-1 emits exactly 9 BackendDecision records.
- Stage-1 emits the records in the order above (1 → 9).
- Each record names a component from §1 exactly once.
- Stage-1 performs no I/O (no NATS connect, no socket open,
  no subprocess launch — the Rust binaries are launched lazily
  by Stage-2 builders).
- Stage-2 builders consume only the Stage-1 decisions; they do
  not re-resolve ENV flags.

---

## 5. Backward-Compatibility Statement

0.5.0-pre-cutover is a **strict superset** of 0.4.2-pilot:

- Every `WAKIR_*_BACKEND` flag from 0.4.2-pilot retains its
  identical accepted-value set and default. No flag is renamed,
  no flag changes its default from `python` to `rust`.
- The boot order from 0.4.2-pilot (records 1–9) is preserved
  byte-for-byte. The Doppelbetrieb boot-fingerprint hash is
  stable.
- The 10th BackendDecision record (`bridge-audit-writer`) is
  **held back** intentionally — wiring it would change the
  boot-fingerprint and break the Phase-3a parity gate just before
  cutover. Tag-46/47 will add it post-cutover behind a feature
  flag.
- The Containerfile image-tag bumps from `0.5.0-pilot` to
  `0.5.0-pre-cutover`. The on-disk layout, entrypoint symlink, and
  Quadlet `Exec=` line are byte-stable.
- ADR-0036 self-migration guarantee: the
  `wirelang.persona_engine.migrate_version` converter recognises
  `0.4.2-pilot → 0.5.0-pre-cutover` as a no-op (no
  persona-definition-format change in this release).

Any operator running 0.4.2-pilot can swap to 0.5.0-pre-cutover by
rotating the Quadlet image tag; no ENV-file edit required.

---

## 6. Cutover Readiness Checklist (Operator-Hand, Tag-46)

Selin's pre-cutover deliverables (this manifest closes the engine
side). Cross-team gates listed for completeness; not all are owned
by the persona-engine box.

- [x] 9-component BackendDecision inventory documented (§1).
- [x] ENV-flag schema consistent, no rename gaps (§2).
- [x] 15-crate pin pack written to
      `infra/persona-engine/pin-pack-0.5.0-pre-cutover.yaml` (§3).
- [x] Boot-sequence diagram + invariant list (§4).
- [x] Containerfile.real bumped to `0.5.0-pre-cutover` image tag.
- [x] Backward-compatibility statement (§5).
- [x] Hermetic manifest-integrity tests (15+) in
      `wirelang/tests/persona_engine/test_manifest_0_5_0_pre_cutover.py`.
- [ ] Cross-substrate-parity-gate green on PR (CI).
- [ ] Operator-hand live-VM rotation from `0.5.0-pilot` to
      `0.5.0-pre-cutover` (Kai / Operator-Hand, Tag-46).
- [ ] OTS-anchor of the manifest hash via WAT spool (Tomás,
      Zone-K cross-review preceding).

---

*Selin Çelik — Persona-Engine-Engineer, Tag-45 closeout 2026-05-18.*
