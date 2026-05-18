<!--
SPDX-License-Identifier: BUSL-1.1
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Business Source License 1.1; see ./LICENSE-BSL.md.
Change Date: 2030-05-15. Change License: Apache License 2.0.
-->

# Wakir Persona-Engine — Manifest 0.5.1-pre-cutover

**Tag-48 (2026-05-19). Bridge-audit-writer wire-in as the 10th BackendDecision record. Strict superset of 0.5.0-pre-cutover (Tag-45).**

This manifest is the single source of truth for the
0.5.1-pre-cutover engine release: which BackendDecision records the
boot path emits (now **ten**), which ENV flags gate each backend,
which cross-language pin-pack vectors anchor the Rust ↔ Python parity
substrates, and which sequence the engine follows from
`engine.__init__` to the first BackendDecision audit emission.

The manifest is intentionally **machine-readable** for the
hermetic Tag-48 integrity tests (see
`wirelang/tests/persona_engine/test_manifest_0_5_1_pre_cutover.py`)
and the cross-substrate parity gate
(`.github/workflows/cross-substrate-parity-gate.yml`).

> **Spec cross-reference (Tag-50, v0.4.2).** This manifest's §2
> ENV-flag schema is the authoritative companion to
> `wirelang/specs/wirelang-spec-v0-4-2.md` §4.1. The two surfaces
> are kept consistent by the hermetic test suite
> `tests/specs/test_wirelang_spec_v0_4_2_drift_s4_reconciliation.py`
> (Tag-50). The `WAKIR_*_BACKEND` selector-ENV naming (no `_PE_`
> infix) and the ten-record boot fan-out ordering are normative
> here; v0.4.2 §4.1 documents the same reality and treats this
> manifest plus the Pin-Pack-0.5.1 YAML as the single source of
> truth.

> **Scope discipline (ADR-0036 / ADR-0043 / ADR-0065 / ADR-0066)** —
> this file documents the engine wiring. It does **not** modify
> persona definitions (Aisha-Domäne), WAT-core logic (Tomás-Domäne),
> identity-substrate design (Reza-Domäne), or container-infra
> beyond the Containerfile version bump (Kai-Domäne).

---

## 1. Component Inventory (10 BackendDecision Records, Boot-Ordered)

The 0.5.1-pre-cutover engine emits **exactly ten** `BackendDecision`
records per cold-start, in the order below. Each record names one
backend module that the engine resolves via
`wirelang.persona_engine.rust_backend_switch.resolve_*`. The previous
0.5.0-pre-cutover manifest held back the 10th component
(`bridge-audit-writer`) as an enum-defined-but-unwired scaffold;
Tag-48 closes the wire-in by extending the engine.py boot fan-out
to consult :func:`resolve_bridge_audit_writer_backend` after
`resolve_federation_resolver_backend` and before opening the
`persona_engine.boot` OTel span.

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
| 10 | bridge-audit-writer | `wirelang.persona_engine.bridge_audit_writer` | `persona-engine-bridge-audit-writer` | `tests/fixtures/bridge-audit-writer-cross-lang/fixtures.json` |

V-907 (record #4) is the **most critical** integrity anchor: any
byte-drift between Python authority and Rust pendant would silently
corrupt the WAT-audit substrate. The bridge-diff oracle (record #5)
is the Phase-3a Doppelbetrieb comparison gate. The new Tag-48
addition (record #10) closes the Doppelbetrieb-Shadow envelope
side of the same loop — the writer-half completes the
diff-oracle/replay-oracle/writer-oracle triangle the Phase-3b
parity gate hashes.

---

## 2. ENV-Flag Schema (Consistent `WAKIR_*_BACKEND` Naming)

Every BackendDecision is gated by **two** ENV flags following the
identical convention: a backend selector (`python` / `rust`, default
`python`) and a Rust-binary path override. A third optional knob
(`WAKIR_RUST_BACKEND_TIMEOUT_S`) caps the subprocess wait across
**all** Rust backends.

### 2.1 Backend Selector ENVs (10 flags, one per component)

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
| federation-resolver | `WAKIR_FEDERATION_RESOLVER_BACKEND` | `python`, `rust` | `python` |
| bridge-audit-writer | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` | `python`, `rust` | `python` |

### 2.2 Rust-Binary Path Override ENVs (10 flags, one per component)

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
| bridge-audit-writer | `WAKIR_RUST_BRIDGE_AUDIT_WRITER_BIN` |

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

### 2.5 Tag-48 Wire-In Closeout

`WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` is no longer held back. The
Stage-1 boot fan-out consults
:func:`resolve_bridge_audit_writer_backend` and emits the 10th
BackendDecision record per cold-start. Operators flipping the
selector to `rust` before the
``wakir-persona-engine-bridge-audit-writer`` binary is installed on
the carrier image will observe a `binary_missing` fallback in the
audit substrate — identical posture to the Tag-25 ADR-0065 Welle-2
precondition signal that landed when SVID-workload-identity was
wired in but the Rust crate had not yet shipped.

---

## 3. Cross-Language Pin-Pack Map (15 Phase-3a Crates @ 0.1.0)

The Tag-48 0.5.1-pre-cutover engine pins **all fifteen** Phase-3a
Rust crates at version `0.1.0` (unchanged from 0.5.0-pre-cutover —
no crate-version bump in this release; the wire-in is engine-only).
The pin pack lives at
`infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml` and is the
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
| 10 | `persona-engine-bridge-audit-writer` | 0.1.0 | record #10 (Tag-48 wire-in) |
| 11 | `persona-engine-bridge-audit-replay` | 0.1.0 | replay-side oracle |
| 12 | `persona-engine-anchor-submit-worker` | 0.1.0 | WAT-spool sibling |
| 13 | `persona-engine-frontmatter-parser` | 0.1.0 | Tag-34 parser substrate |
| 14 | `persona-engine-bridge-forward` | 0.1.0 | Python ↔ Rust forward pipe |
| 15 | `persona-engine-federation-frame-parser` | 0.1.0 | federation-frame oracle |

Records #1–10 are wired into the boot sequence and emit a
`BackendDecision` per cold-start. Records #11–15 are byte-parity
substrates that ship in 0.5.1-pre-cutover for cross-substrate
validation (cross-substrate-parity-gate workflow) but are consumed
only when explicitly invoked from the Python authority side.

---

## 4. Boot-Sequence Diagram

The engine `__init__` resolves the ten backends in a fixed,
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
│  1. resolve_recovery_backend()           → decision #1    │
│  2. resolve_state_backing_backend()      → decision #2    │
│  3. resolve_fsm_backend()                → decision #3    │
│  4. resolve_v907_verify_backend()        → decision #4    │
│  5. resolve_bridge_diff_backend()        → decision #5    │
│  6. resolve_subscribe_loop_backend()     → decision #6    │
│  7. resolve_anchor_emitter_backend()     → decision #7    │
│  8. resolve_svid_workload_identity_…()   → decision #8    │
│  9. resolve_federation_resolver_…()      → decision #9    │
│ 10. resolve_bridge_audit_writer_…()      → decision #10   │
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
│  • build_bridge_audit_writer(...)  ← Tag-48 sibling slot   │
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
`test_manifest_0_5_1_pre_cutover.py` and `test_bridge_audit_writer_wire_in_tag48.py`):

- Stage-1 emits exactly 10 BackendDecision records.
- Stage-1 emits the records in the order above (1 → 10).
- Each record names a component from §1 exactly once.
- Stage-1 performs no I/O (no NATS connect, no socket open,
  no subprocess launch — the Rust binaries are launched lazily
  by Stage-2 builders).
- Stage-2 builders consume only the Stage-1 decisions; they do
  not re-resolve ENV flags.

---

## 5. Backward-Compatibility Statement

0.5.1-pre-cutover is a **strict superset** of 0.5.0-pre-cutover:

- Every `WAKIR_*_BACKEND` flag from 0.5.0-pre-cutover retains its
  identical accepted-value set and default. No flag is renamed,
  no flag changes its default from `python` to `rust`.
- The boot order from 0.5.0-pre-cutover (records 1–9) is preserved
  byte-for-byte. The Doppelbetrieb boot-fingerprint hash for the
  first 9 records is stable; the new record #10
  (`bridge-audit-writer`) extends the fingerprint with one
  additional 4-tuple at the tail
  ``("bridge_audit_writer", "python", "python", None)`` under
  clean env.
- `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND` was previously defined but
  not consulted by boot (0.5.0-pre-cutover §5 held it back).
  0.5.1-pre-cutover consults it as the 10th resolver call. The
  default value is still `python`; operators who never set the
  ENV see no observable behaviour change beyond one extra
  ``backend-decision`` line in the audit log.
- The Containerfile image-tag bumps from `0.5.0-pre-cutover` to
  `0.5.1-pre-cutover`. The on-disk layout, entrypoint symlink, and
  Quadlet `Exec=` line are byte-stable.
- ADR-0036 self-migration guarantee: the
  `wirelang.persona_engine.migrate_version` converter recognises
  `0.5.0-pre-cutover → 0.5.1-pre-cutover` as a no-op (no
  persona-definition-format change in this release).

Any operator running 0.5.0-pre-cutover can swap to 0.5.1-pre-cutover
by rotating the Quadlet image tag; no ENV-file edit required. The
only observable post-rotation drift is the appearance of a tenth
``backend-decision`` JSON line per boot — by design.

---

## 6. Cutover Readiness Checklist (Operator-Hand, Tag-48)

Selin's pre-cutover deliverables (this manifest closes the engine
side at 10 records). Cross-team gates listed for completeness; not
all are owned by the persona-engine box.

- [x] 10-component BackendDecision inventory documented (§1).
- [x] ENV-flag schema consistent, no rename gaps (§2).
- [x] 15-crate pin pack written to
      `infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml` (§3).
- [x] Boot-sequence diagram + invariant list (§4, ten-record edition).
- [x] Containerfile.real bumped to `0.5.1-pre-cutover` image tag.
- [x] Backward-compatibility statement (§5).
- [x] Hermetic manifest-integrity tests (15+) in
      `wirelang/tests/persona_engine/test_manifest_0_5_1_pre_cutover.py`.
- [x] Hermetic wire-in tests (15+) in
      `wirelang/tests/persona_engine/test_bridge_audit_writer_wire_in_tag48.py`.
- [ ] Cross-substrate-parity-gate green on PR (CI).
- [ ] Operator-hand live-VM rotation from `0.5.0-pre-cutover` to
      `0.5.1-pre-cutover` (Kai / Operator-Hand, Tag-49).
- [ ] OTS-anchor of the manifest hash via WAT spool (Tomás,
      Zone-K cross-review preceding).

---

*Selin Çelik — Persona-Engine-Engineer, Tag-48 wire-in 2026-05-19.*
