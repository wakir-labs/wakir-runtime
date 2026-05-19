<!--
SPDX-License-Identifier: BUSL-1.1
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Business Source License 1.1; see ./LICENSE-BSL.md.
Change Date: 2030-05-15. Change License: Apache License 2.0.
-->

# Wakir Persona-Engine — Manifest 0.5.2-final-pre-cutover

**Tag-52 (2026-05-19). Pre-KW-24 Final Consolidation. Strict superset of
0.5.1-pre-cutover (Tag-48). No new boot record; no flag rename; no flag
default flip. The 0.5.2-final marker is the Pre-Cutover-Final anchor for
the KW-24 cutover gate.**

This manifest is the single source of truth for the
0.5.2-final-pre-cutover engine release — the last pre-cutover manifest
emitted before the Phase-3c cutover window opens in KW 24. It absorbs
the Tag-48 wire-in (record #10 bridge-audit-writer), the Tag-50 DRIFT-S4
reconciliation (Pin-Pack-0.5.1 as the spec-§4.1 source of truth under
v0.4.2), and the Tag-51 10-Decision-Engine-Resilience formalisation as
the resilience-substrate-pin for the cutover window. It does **not**
add a new BackendDecision record, does **not** rename a flag, does
**not** flip a flag default, and does **not** bump any crate version.

The version bump from `0.5.1-pre-cutover` to `0.5.2-final-pre-cutover`
is a **manifest-and-metadata-only** consolidation marker. The image
on-disk layout, the entrypoint symlink, the Quadlet `Exec=` line, the
boot fan-out order, and the 15-crate cross-language pin set are all
byte-stable vs. 0.5.1-pre-cutover.

The manifest is intentionally **machine-readable** for the hermetic
Tag-52 integrity tests (see
`wirelang/tests/persona_engine/test_manifest_0_5_2_final_pre_cutover.py`)
and the cross-substrate parity gate
(`.github/workflows/cross-substrate-parity-gate.yml`).

> **Spec cross-reference (Tag-50, v0.4.2).** This manifest's §2
> ENV-flag schema is byte-identical to the 0.5.1-pre-cutover schema
> and remains the authoritative companion to
> `wirelang/specs/wirelang-spec-v0-4-2.md` §4.1. The two surfaces
> are kept consistent by the hermetic test suite
> `tests/specs/test_wirelang_spec_v0_4_2_drift_s4_reconciliation.py`
> (Tag-50). The `WAKIR_*_BACKEND` selector-ENV naming (no `_PE_`
> infix) and the ten-record boot fan-out ordering are normative
> here; v0.4.2 §4.1 documents the same reality and treats this
> manifest plus the Pin-Pack-0.5.2 YAML as the single source of
> truth.

> **Resilience cross-reference (Tag-51).** The 10-Decision-Engine-
> Resilience suite (`wirelang/tests/persona_engine/test_tag51_10_decision_engine_resilience.py`,
> 36 hermetic tests) is the resilience-substrate-pin for the
> cutover window. It asserts that under every degraded-backend
> posture — Rust-binary-missing, subprocess-timeout, validation-
> error — Stage-1 still emits exactly ten BackendDecision records
> in the canonical boot order. The 0.5.2-final manifest pins
> Tag-51's contract by reference; any future flag-rename or
> boot-order change must update Tag-51's expectation tables in
> lockstep.

> **Scope discipline (ADR-0036 / ADR-0043 / ADR-0065 / ADR-0066)** —
> this file documents the engine wiring. It does **not** modify
> persona definitions (Aisha-Domäne), WAT-core logic (Tomás-Domäne),
> identity-substrate design (Reza-Domäne), or container-infra
> beyond the Containerfile version-bump label (Kai-Domäne).

---

## 0. Version Header (Tag-58, 0.5.3-rc1)

**Tag-58 (2026-05-19, Selin / Persona-Engine). Final Pre-Cutover RC
before KW-24 cutover gate opens.** This §0 section pins the active
engine version that consumes this manifest. The manifest body (§1–§7)
remains byte-stable vs. its Tag-52 emit; the only change introduced
by Tag-58 is the version-header marker recorded here so the hermetic
version-consistency tests have a single docstring anchor to assert
against.

| Field | Value |
|---|---|
| Engine version (Python source of truth) | `0.5.3-rc1` |
| Module anchor | `wirelang/persona_engine/__version__.py` |
| Manifest file | `wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md` (this file) |
| Pin pack (machine-readable) | `infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml` |
| Release notes | `docs/persona-engine/0-5-3-rc1-release-notes.md` |
| Strict superset of | `0.5.2-final-pre-cutover` (Tag-52, PR #335) |
| Carry-forward closeouts | Tag-57 OPEN-K1, OPEN-K2 (Tomás PR #366); Tag-57 OPEN-J1 (Kai PR #367); Tag-57 emit-order pin (Selin PR #363) |
| Remaining open item | OPEN-J2 (Operator-Hand, cutover-day live-VM) |
| Boot fan-out byte-shape | unchanged vs. 0.5.2-final — ten records, canonical order |

The 0.5.3-rc1 bump is **manifest-and-metadata-only**. It does **not**:

* add or remove a `BackendDecision` record;
* rename an ENV flag;
* flip an ENV-flag default;
* bump any crate version in the 15-crate cross-language pin pack;
* alter the boot fan-out order pinned in Tag-57 PR #363.

It only:

* factors the Python version string from inline literals in
  `__init__.py` + `engine.py` into the canonical
  `wirelang/persona_engine/__version__.py` anchor;
* stamps `0.5.3-rc1` at all four authority surfaces (this §0,
  `__version__.py`, the release-notes file, and the test pin);
* records the Tag-57 closeout chain as the absorbed substrate.

> **Scope discipline (Selin).** This §0 documents the engine
> version-bump only. It does **not** modify persona definitions
> (Aisha-Domäne, ADR-0043), WAT-core logic (Tomás-Domäne, Zone-K),
> identity-substrate design (Reza-Domäne, Zone-L), or container-
> infra (Kai-Domäne, Zone-J). The Cross-Review Zone-J/K/L Konsens
> from Tag-56 audit (PR #362) and Tag-57 closeout chain
> (PR #366, #367) is carried forward unchanged; no fresh Cross-
> Review gate is opened by this bump.

---

## 1. Component Inventory (10 BackendDecision Records, Boot-Ordered)

The 0.5.2-final-pre-cutover engine emits **exactly ten**
`BackendDecision` records per cold-start, in the order below. The
table is byte-stable vs. 0.5.1-pre-cutover §1 — no record added, no
record removed, no record renamed.

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

V-907 (record #4) is the most critical integrity anchor. The
bridge-diff oracle (record #5) is the Phase-3a Doppelbetrieb
comparison gate. The bridge-audit-writer (record #10) closes the
diff/replay/writer triangle the Phase-3b parity gate hashes.

---

## 2. ENV-Flag Schema (Consistent `WAKIR_*_BACKEND` Naming)

Every BackendDecision is gated by **two** ENV flags following the
identical convention: a backend selector (`python` / `rust`, default
`python`) and a Rust-binary path override. A third optional knob
(`WAKIR_RUST_BACKEND_TIMEOUT_S`) caps the subprocess wait across
**all** Rust backends. The schema is byte-stable vs. 0.5.1-pre-cutover.

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

### 2.5 Legacy ENV detection (Tag-51 Reza-substrate)

Operators who still set the **legacy** `WAKIR_PE_*_BACKEND` names
(superseded under v0.4.2 §5.6) are detected at boot via the Tag-51
legacy-migration-detector hook
(`wirelang.persona_engine.legacy_env_migration_detector`). The
detector emits one structured-log warning per legacy flag and does
**not** fall back to the legacy name — the unset canonical flag
keeps its `python` default. Operators see the warning, rotate the
ENV file to the canonical names, and the warning disappears on the
next cold-start.

---

## 3. Cross-Language Pin-Pack Map (15 Phase-3a Crates @ 0.1.0)

The Tag-52 0.5.2-final-pre-cutover engine pins **all fifteen**
Phase-3a Rust crates at version `0.1.0` — byte-stable vs.
0.5.1-pre-cutover. No crate-version bump in this release; the
0.5.2-final marker is a consolidation marker, not a crate-bump
release. The pin pack lives at
`infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml` and is
the machine-readable counterpart to the table below.

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
| 10 | `persona-engine-bridge-audit-writer` | 0.1.0 | record #10 |
| 11 | `persona-engine-bridge-audit-replay` | 0.1.0 | replay-side oracle |
| 12 | `persona-engine-anchor-submit-worker` | 0.1.0 | WAT-spool sibling |
| 13 | `persona-engine-frontmatter-parser` | 0.1.0 | Tag-34 parser substrate |
| 14 | `persona-engine-bridge-forward` | 0.1.0 | Python ↔ Rust forward pipe |
| 15 | `persona-engine-federation-frame-parser` | 0.1.0 | federation-frame oracle |

Records #1–10 are wired into the boot sequence and emit a
`BackendDecision` per cold-start. Records #11–15 are byte-parity
substrates that ship in 0.5.2-final-pre-cutover for cross-substrate
validation (cross-substrate-parity-gate workflow) but are consumed
only when explicitly invoked from the Python authority side.

---

## 4. Boot-Sequence Diagram

The engine `__init__` resolves the ten backends in a fixed,
deterministic order. Re-ordering would invalidate the
boot-fingerprint that the Doppelbetrieb oracle hashes for the
Phase-3a parity gate; any change here is an ADR-level decision.
Byte-stable vs. 0.5.1-pre-cutover §4.

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
`test_manifest_0_5_2_final_pre_cutover.py` and the Tag-51
resilience suite `test_tag51_10_decision_engine_resilience.py`):

- Stage-1 emits exactly 10 BackendDecision records.
- Stage-1 emits the records in the order above (1 → 10).
- Each record names a component from §1 exactly once.
- Stage-1 performs no I/O.
- Stage-2 builders consume only the Stage-1 decisions; they do
  not re-resolve ENV flags.
- The boot-fingerprint hash for clean-env cold-start is
  byte-identical between 0.5.1-pre-cutover and 0.5.2-final-pre-cutover
  (the 0.5.2-final marker does not alter the audit log shape).

---

## 5. Backward-Compatibility Statement

0.5.2-final-pre-cutover is a **strict superset** of 0.5.1-pre-cutover:

- Every `WAKIR_*_BACKEND` flag from 0.5.1-pre-cutover retains its
  identical accepted-value set and default. No flag is renamed,
  no flag changes its default from `python` to `rust`.
- The boot order from 0.5.1-pre-cutover (records 1–10) is preserved
  byte-for-byte. The Doppelbetrieb boot-fingerprint hash is stable
  under clean env.
- All ten Stage-2 substrate builders are byte-identical to
  0.5.1-pre-cutover.
- The Containerfile image-tag bumps from `0.5.1-pre-cutover` to
  `0.5.2-final-pre-cutover`. The on-disk layout, entrypoint symlink,
  and Quadlet `Exec=` line are byte-stable.
- ADR-0036 self-migration guarantee: the
  `wirelang.persona_engine.migrate_version` converter recognises
  `0.5.1-pre-cutover → 0.5.2-final-pre-cutover` as a no-op (no
  persona-definition-format change in this release).
- The Tag-51 resilience contract (`test_tag51_10_decision_engine_resilience.py`,
  36 tests) is pinned by reference and must continue to pass with
  the 0.5.2-final manifest in place.
- The Tag-50 spec-v0.4.2 §4.1 source-of-truth invariant
  (Pin-Pack is the SoT for the §4.1 ENV-flag schema) is reaffirmed
  — the 0.5.2-final pin-pack agrees with the v0.4.2 §4.1 table
  byte-for-byte (modulo the manifest-version field).

Any operator running 0.5.1-pre-cutover can swap to
0.5.2-final-pre-cutover by rotating the Quadlet image tag; no
ENV-file edit required. No observable audit-log change beyond the
image-version label.

---

## 6. Pre-KW-24 Cutover Readiness Checklist

Selin's pre-cutover deliverables consolidated under the 0.5.2-final
marker. Cross-team gates listed for completeness; not all are owned
by the persona-engine box.

- [x] 10-component BackendDecision inventory byte-stable vs. 0.5.1 (§1).
- [x] ENV-flag schema byte-stable vs. 0.5.1, no rename gaps (§2).
- [x] Legacy `WAKIR_PE_*_BACKEND` detection hook (Tag-51 Reza) — §2.5.
- [x] 15-crate pin pack byte-stable vs. 0.5.1, written to
      `infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml` (§3).
- [x] Boot-sequence diagram + invariant list (§4, ten-record edition).
- [x] Containerfile.real bumped to `0.5.2-final-pre-cutover` image tag.
- [x] Backward-compatibility statement (§5).
- [x] Hermetic manifest-integrity tests (≥15) in
      `wirelang/tests/persona_engine/test_manifest_0_5_2_final_pre_cutover.py`.
- [x] Tag-51 resilience contract pinned by reference (§4 invariant list).
- [x] Tag-50 spec-v0.4.2 §4.1 SoT invariant reaffirmed (§5).
- [ ] Cross-substrate-parity-gate green on PR (CI).
- [ ] Operator-hand live-VM rotation from `0.5.1-pre-cutover` to
      `0.5.2-final-pre-cutover` (Kai / Operator-Hand, KW-24 window).
- [ ] OTS-anchor of the manifest hash via WAT spool (Tomás,
      Zone-K cross-review preceding).
- [ ] Cutover-window-open signal (Mira / AR / Operator-Hand, KW-24).

---

## 7. Sources Absorbed Under 0.5.2-final

| Source | What it pins | How 0.5.2-final absorbs it |
|---|---|---|
| MANIFEST-0.5.1-pre-cutover.md (Tag-48 PR #313) | Bridge-audit-writer wire-in, 10-record inventory | §1, §2, §4 byte-stable carry-over |
| pin-pack-0.5.1-pre-cutover.yaml (Tag-48 PR #313) | 15-crate pin set, 10 wired + 5 unwired | §3 byte-stable carry-over |
| wirelang-spec-v0-4-2.md §4.1 (Tag-50 PR #320) | DRIFT-S4 reconciliation, Pin-Pack as SoT | §2 schema reaffirmed, §5 SoT-invariant note |
| test_tag51_10_decision_engine_resilience.py (Tag-51 PR #327) | Resilience contract under degraded backends | §4 invariant list pinned by reference |
| legacy_env_migration_detector (Tag-51 PR #329 Reza) | `WAKIR_PE_*_BACKEND` legacy-flag detection | §2.5 note |

The 0.5.2-final marker is the consolidation-anchor that the KW-24
cutover gate hashes. No artefact from Tag-48..51 is rewritten —
all sources stay in-tree as historical anchors; the 0.5.2-final
manifest references them via §7 above.

---

*Selin Çelik — Persona-Engine-Engineer, Tag-52 Pre-KW-24 Final
Consolidation, 2026-05-19.*
