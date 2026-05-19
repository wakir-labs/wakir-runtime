<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

# Persona-Engine 0.5.3 Production-Readiness Audit (Tag-63, Post-Final-Bump)

- **Generated:** 2026-05-19T13:45:00+02:00 (Tag-63, Continuous-Mode,
  AR-persistent dispatch, Marathon).
- **Audit class:** static cross-reference walk + hermetic test
  verification, no NATS, no engine boot, no Rust compile, no
  network, no subprocess. Pure tree-walk + YAML parse + file
  inspection.
- **Audit baseline (main tip after FF):** `e74ea17` — Tag-62
  Engine 0.5.3 final-bump pre-cutover-sealing (Selin, PR #399).
  Post-merge of #399 (rc1 → final rc1-suffix-drop), #398
  (Pyramide-Acceptance Pre-Cutover Compositum, Amara), #397
  (Watch-Day Operator-Trigger-Pipeline, Noa), #396 (Tag-62
  pre-walk recipe for 7-pool required-checks), #395 (wakir-
  protocol Cross-Review-Zone-3 hand-off plan, Reza), #394
  (REUSE-Wrap enforce-flip-readiness plan, Tomás).
- **Auftrag baseline:** Mira (CEO) Tag-63 dispatch, post-Final-
  Bump production-readiness verification of the
  `0.5.3` release substrate.
- **Spec under audit:** Persona-Engine `0.5.3` final
  release substrate (manifest §0 v0.5.3 header + Tag-52
  manifest §1..§7 body carry-forward + pin-pack + Containerfile +
  Cargo workspace + Python authority surface). The `0.5.3`
  final tag is the **rc1-suffix-drop** of `0.5.3-rc1` (Tag-58,
  PR #372) — a manifest-and-metadata-only seal in preparation
  for the KW-24 cutover-T0 window (2026-06-08/09).
- **Author role:** Persona-Engine-Engineer (Selin).
- **Cutover gate context:** KW-24 (week 24) cutover window opens
  in 4 calendar days (T0 = 2026-06-08/09). `0.5.3` is the final
  pre-cutover release tag; the next bump after `0.5.3` is the
  cutover image itself.

> **Scope discipline (ADR-0036 / ADR-0043 / ADR-0065 / ADR-0066)** —
> this audit reads the engine wiring. It does **not** modify
> persona definitions (Aisha-Domäne), WAT-core logic (Tomás-Domäne,
> Zone-K), identity-substrate design (Reza-Domäne, Zone-L), or
> container-infra beyond reading the Containerfile shape
> (Kai-Domäne, Zone-J). Zone-J cross-review (Kai-container-bridge),
> Zone-K (Tomás-WAT-V-907), and Zone-L (Reza-identity) findings
> are flagged but not patched.

> **Relationship to Tag-56 audit (PR #362).** This Tag-63 audit is
> the post-Final-Bump counterpart of the Tag-56 0.5.2-final-pre-
> cutover audit. Audit pattern, dimension list, and verdict
> categories are deliberately byte-stable vs. Tag-56 so a
> side-by-side diff highlights only what changed between
> `0.5.2-final-pre-cutover` and `0.5.3`. Spoiler: nothing in
> dimensions D1..D7 changed, because `0.5.3` is a metadata-only
> rc1-suffix-drop.

---

## 1. Executive Summary

**Verdict: PRODUCTION-READY-WITH-OPEN.**

The `0.5.3` final release substrate is internally consistent and
a strict byte-superset of `0.5.3-rc1` (Tag-58, PR #372), which is
itself a strict byte-superset of `0.5.2-final-pre-cutover` (Tag-52,
PR #335). All seven audit dimensions pass independently and
cross-reference cleanly:

1. **10-BackendDecision inventory** — the manifest §1 inventory
   table (Tag-52 body, carry-forward), the pin-pack
   `boot_wired_crates` list, and the
   `wirelang/persona_engine/engine.py` `__init__`/`boot` resolver
   fan-out agree byte-for-byte. Records 1..10 are present, ordered,
   and each names exactly one Python authority + one Rust pendant
   crate + one cross-lang fixture path. Triply-witnessed.
2. **15-crate cross-language pin pack** — all 15 crates exist
   under `wirelang-rust/crates/`, all are pinned at version
   `0.1.0` (byte-stable vs. 0.5.2-final-pre-cutover and vs.
   0.5.3-rc1), and all 15 appear in `wirelang-rust/Cargo.toml`
   `members =`. No crate-version bump in the 0.5.3 final seal.
3. **ENV-flag consistency** — manifest §2.1 selector ENVs (10
   flags), §2.2 binary-path ENVs (10 flags), and §2.3 cross-backend
   timeout (1 flag) all use the canonical `WAKIR_*_BACKEND` /
   `WAKIR_RUST_*_BIN` naming. The legacy `WAKIR_PE_*_BACKEND`
   surface is detected and warn-no-fallback-handled by the Tag-51
   Reza migration-detector (pin-pack §2.5).
4. **FSM state-diagram (Rust pendant)** — six states
   (`uninstantiated`, `spawning`, `running`, `despawning`,
   `recovered`, `migrated`) + nine valid transitions present in
   `wirelang-rust/crates/persona-engine-fsm/src/lib.rs`
   `VALID_TRANSITIONS`. Matches spec §3.3 by row count and edge
   tuple. Cross-lang fixture path resolves.
5. **V-907 pin-stability substrate** — the four V-907-relevant
   Rust crates (`persona-hash`, `persona-canonical-form`,
   `persona-canonical-form-yaml`, `persona-engine-v907-verify`)
   all exist; the V-907-verify crate-doc pins the SAMPLE_AXIS_A
   ground-truth digest
   `sha256:cf66fbc5e02ebee97726d5903460e1c3b2b20d1e10db6db1083bceb62ede6e39`
   (Tag-25 reza-Cross-Review-Tag-34/35 anchored). The Tag-59
   V-907 composite-hash seal at
   `wirelang/persona_engine/v907-hash-baseline.json` is unchanged
   and survives the 0.5.3 final-bump (the §0 version-header is
   outside the V-907-bounded byte-range, as documented in the
   release-notes §1).
6. **Containerfile.real layer integrity** — 21 instructions
   (1 FROM, 7 LABEL, 7 COPY, 3 RUN, 1 USER, 1 WORKDIR, 1
   ENTRYPOINT). Image-tag label is `0.5.2-final-pre-cutover`
   (carry-forward; see OPEN-J3 below). Entrypoint symlink chain
   (`persona-engine -> persona-engine-real`) is byte-stable.
7. **Cargo workspace** — 32 workspace members in `wirelang-rust/
   Cargo.toml`, all paths resolve to a Cargo.toml on-disk. Six
   byte-stability-relevant workspace dependencies (`sha2`,
   `serde`, `serde_json`, `serde_jcs`, `serde_yaml`, `hex`) are
   all strict-equality-pinned (`=X.Y.Z`).

The open items are **cross-team pendencies, not engine
defects**:

- **OPEN-J2 (Zone-J, Operator-Hand):** KW-24 cutover-day live-VM
  rotation. Carry-forward from Tag-56 OPEN-J2. The Tag-57 OPEN-K1
  + OPEN-K2 (Tomás, PR #366) and OPEN-J1 (Kai, PR #367) closeouts
  reduced the Tag-56 5-item tracker to a single non-Selin gate.
  Severity: blocker-for-cutover (not blocker-for-final-pre-cutover).
- **OPEN-J3 (Zone-J, label-carry-forward):** Containerfile.real
  carries the OCI `image.version="0.5.2-final-pre-cutover"` label
  as carry-forward. This is intentional under the Tag-62 scope
  discipline — Selin's 0.5.3 final-bump is **manifest-and-
  metadata-only** and does not touch infra/persona-engine/
  Containerfile.real (Kai-Zone-J domain). The label refresh is
  Kai's gate. Severity: blocker-for-cutover-image-build (not
  blocker-for-the-0.5.3-substrate-itself).
- **OPEN-K3 (Zone-K, Tomás):** V-907 composite-hash baseline at
  `v907-hash-baseline.json` still carries `engine_version:
  "0.5.3-rc1"` by design. Refresh requires Selin-Hand + Tomás-
  Zone-K cross-review per the Tag-59 seal contract (the baseline
  is itself the Zone-K cross-review artefact). This is the same
  posture documented in `0-5-3-final-release-notes.md` §1 line
  3-4 ("No persona-definition change ... refreshing it requires
  Selin-Hand + Tomas-Zone-K cross-review per the Tag-59 seal
  contract.").

No drift, no spec-conflict, no rename-gap, no flag-default flip,
no byte-stability violation vs. `0.5.3-rc1` and vs.
`0.5.2-final-pre-cutover`. The `0.5.3` final marker is a
**manifest-and-metadata-only** rc1-suffix-drop exactly as the
Tag-62 release-notes §1 self-description claims (four surface-
level changes: version literal, Tag-59 hot-fix-surface mirroring,
Manifest §0 rewrite, drift-scanner allowlist extension).

The verdict **PRODUCTION-READY-WITH-OPEN** is one notch stronger
than the Tag-56 verdict **PRODUCTION-READY-WITH-2-OPEN-CROSS-
REVIEW-ITEMS** because Tag-56 had two Zone-K cross-review items
on the critical path (OPEN-K1 base-image digest, OPEN-K2 OTS-
anchor) plus two Zone-J items (OPEN-J1 parity gate, OPEN-J2 live-
VM rotation), all open. Tag-63 carries forward only one
substantive open item (OPEN-J2 live-VM rotation) plus two
intentional-by-design carry-forwards (OPEN-J3 label, OPEN-K3
baseline refresh).

---

## 2. Audit Method

Static substrate-consistency audit. For every claim in the
Tag-52 manifest (`MANIFEST-0.5.2-final-pre-cutover.md`, §0
updated by Tag-62 to record `0.5.3`), the
`pin-pack-0.5.2-final-pre-cutover.yaml` (carry-forward), and
the new Tag-62 surfaces (`docs/persona-engine/0-5-3-final-
release-notes.md`, `wirelang/persona_engine/__version__.py`,
`wirelang/persona_engine/engine.py` import comment,
`wirelang/persona_engine/engine_async.py` `ASYNC_ENGINE_VERSION`,
`wirelang/persona_engine/cli.py` docstring), we cross-check
three independent witnesses:

- the YAML / Markdown source-of-truth files,
- the Python authority modules under `wirelang/persona_engine/`,
- the Rust crate manifests under `wirelang-rust/crates/<name>/`.

The audit is deterministic and reproducible. The hermetic test
suite
`wirelang/tests/persona_engine/test_tag63_production_readiness_audit.py`
encodes every numeric and string assertion in this report; a
divergence between this document and the substrate trips the
suite in the next CI cycle.

The audit does **not**:

- start NATS, JetStream, or any subprocess,
- compile any Rust crate (the workspace state is read via
  `Cargo.toml` text inspection only),
- exercise the engine `__init__` (the boot order is read from
  source-grep of `engine.py`),
- exercise the FSM transitions (the `VALID_TRANSITIONS` table is
  read by source-grep of `persona-engine-fsm/src/lib.rs`),
- touch the SVID-Workload-API, the Federation-Resolver, or any
  network surface.

---

## 3. Audit Findings (Seven Dimensions)

### 3.1 Dimension 1 — 10 BackendDecision Records

**Verdict: MATCH.** Triply-witnessed.

The Tag-52 manifest §1 inventory enumerates ten components in
canonical boot order:

| # | Component | Python Authority Module | Rust Pendant Crate |
|---|---|---|---|
| 1 | recovery-workflow | `wirelang.persona_engine.recovery_workflow` | `persona-engine-recovery` |
| 2 | state-backing | `wirelang.persona_engine.state_backing` | `persona-engine-state-backing` |
| 3 | lifecycle-fsm | `wirelang.persona_engine.lifecycle_state_machine` | `persona-engine-fsm` |
| 4 | v907-verify | `wirelang.persona_engine.v907_verify` | `persona-engine-v907-verify` |
| 5 | bridge-diff | `wirelang.persona_engine.bridge_audit_diff_engine` | `persona-engine-bridge-diff` |
| 6 | subscribe-loop | `wirelang.persona_engine.subscribe_ack` | `persona-engine-subscribe-loop` |
| 7 | anchor-emitter | `wirelang.persona_engine.anchor_emitter` | `persona-engine-anchor-emitter` |
| 8 | svid-workload-identity | `wirelang.persona_engine.svid_workload_identity` | `persona-engine-svid-workload-identity` |
| 9 | federation-resolver | `wirelang.identity.federation_resolver_canonical` | `persona-engine-federation-resolver` |
| 10 | bridge-audit-writer | `wirelang.persona_engine.bridge_audit_writer` | `persona-engine-bridge-audit-writer` |

The three independent witnesses agree:

- **Manifest §1** (Tag-52 body, byte-stable; §0 header is the
  only Tag-62 change) — table above (10 rows).
- **Pin-pack `boot_wired_crates`** — 10 entries, records 1..10,
  each with `python_authority` + `selector_env` + `binary_env` +
  `fixtures` keys. Order matches §1 row-for-row.
- **`engine.py`** — calls `resolve_recovery_backend`,
  `resolve_state_backing_backend`, `resolve_fsm_backend`,
  `resolve_v907_verify_backend`, `resolve_bridge_diff_backend`,
  `resolve_subscribe_loop_backend`, `resolve_anchor_emitter_backend`,
  `resolve_svid_workload_identity_backend`,
  `resolve_federation_resolver_backend`,
  `resolve_bridge_audit_writer_backend`. All ten resolver call-
  sites present.

Every Python authority module exists on-disk under
`wirelang/persona_engine/` (or `wirelang/identity/` for the
federation-resolver-canonical sibling, per the Zone-L
canonicalisation that landed under PR #188).

Every Rust pendant crate exists on-disk under
`wirelang-rust/crates/<crate>/Cargo.toml`.

**Emit-timing nuance (carry-forward from Tag-56 audit, NOT a
finding):** the manifest §1 canonical-order indices describe the
**logical decision-record order**. The actual audit-log emit-
order surfaces `state_backing` first because `state_backing`
resolves inside `PersonaEngine.__init__`, while the other nine
resolve later inside `PersonaEngine.boot()`. The Tag-51 resilience
suite (`test_10_decision_resilience.py`) is the source-of-truth
witness for this layout: `DECISION_ORDER` (10 entries) is the
canonical record-set, and `BOOT_FAN_OUT_DECISIONS = DECISION_ORDER
minus state_backing` (9 entries) is the set that runs in `boot()`.
Tag-57 PR #363 pinned the `state_backing` pre-boot emit-order
explicitly. No correction needed; the substrate is internally
consistent.

### 3.2 Dimension 2 — 15-Crate Cross-Language Pin Pack

**Verdict: MATCH.**

The pin-pack lists 15 crates (10 wired + 5 unwired). All 15
exist under `wirelang-rust/crates/`, all are pinned at version
`0.1.0`, and all 15 are listed in `wirelang-rust/Cargo.toml`
`members =`.

| # | Crate | Version Pinned | On-Disk Cargo.toml | Workspace Member |
|---|---|---|---|---|
| 1 | persona-engine-recovery | 0.1.0 | yes | yes |
| 2 | persona-engine-state-backing | 0.1.0 | yes | yes |
| 3 | persona-engine-fsm | 0.1.0 | yes | yes |
| 4 | persona-engine-v907-verify | 0.1.0 | yes | yes |
| 5 | persona-engine-bridge-diff | 0.1.0 | yes | yes |
| 6 | persona-engine-subscribe-loop | 0.1.0 | yes | yes |
| 7 | persona-engine-anchor-emitter | 0.1.0 | yes | yes |
| 8 | persona-engine-svid-workload-identity | 0.1.0 | yes | yes |
| 9 | persona-engine-federation-resolver | 0.1.0 | yes | yes |
| 10 | persona-engine-bridge-audit-writer | 0.1.0 | yes | yes |
| 11 | persona-engine-bridge-audit-replay | 0.1.0 | yes | yes |
| 12 | persona-engine-anchor-submit-worker | 0.1.0 | yes | yes |
| 13 | persona-engine-frontmatter-parser | 0.1.0 | yes | yes |
| 14 | persona-engine-bridge-forward | 0.1.0 | yes | yes |
| 15 | persona-engine-federation-frame-parser | 0.1.0 | yes | yes |

The `invariants:` block in the pin-pack YAML declares
`total_wired_crates: 10`, `total_pin_pack_crates: 15`,
`boot_record_count: 10`, `manifest_present:
wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md`,
`containerfile_image_tag: 0.5.2-final-pre-cutover`,
`byte_stable_versus: 0.5.1-pre-cutover`. All six invariants are
verified true at main-tip `e74ea17`.

Strict-superset check vs. `0.5.3-rc1` and vs. `0.5.2-final-pre-
cutover`: every crate version is byte-stable — the pin pack YAML
was not modified by Tag-62. The pin-pack filename
(`pin-pack-0.5.2-final-pre-cutover.yaml`) intentionally carries
the Tag-52 version anchor; Tag-62 release-notes §1 explicitly
documents that the pin-pack YAML is carry-forward and that
"no pin-pack YAML refresh" is in scope for the 0.5.3 final bump.

### 3.3 Dimension 3 — ENV-Flag Consistency

**Verdict: MATCH-WITH-3-DOCUMENTED-SIBLING-FLAGS.**

The manifest §2.1 selector ENVs and §2.2 binary-path ENVs both
contain ten flags, paired one-to-one with the ten BackendDecision
records. All twenty flags follow the canonical `WAKIR_*_BACKEND`
/ `WAKIR_RUST_*_BIN` naming convention — no `_PE_` infix anywhere
in the canonical surface.

Cross-checked against the Python-side flag definitions in
`wirelang/persona_engine/rust_backend_switch.py`:

- 10 selector-ENV constants present and named identically.
- 10 binary-path-ENV constants present and named identically.
- 1 cross-backend timeout (`WAKIR_RUST_BACKEND_TIMEOUT_S`) present.

**Documented sibling-surface flags (NOT a finding, documented
for completeness, carry-forward from Tag-56 audit):**
`rust_backend_switch.py` also defines two additional sibling-
surface ENV flags that are **not** part of the ten-record boot
fan-out:

- `WAKIR_BRIDGE_AUDIT_REPLAY_BACKEND` +
  `WAKIR_RUST_BRIDGE_AUDIT_REPLAY_BIN` — replay-side oracle,
  consumed lazily from Python (pin-pack unwired record #11).
- `WAKIR_MIGRATE_VERSION_BACKEND` +
  `WAKIR_RUST_MIGRATE_VERSION_BIN` — Self-Migration-Konverter
  (ADR-0036) sibling, consumed only on persona-format-version-
  change, not at engine boot.

Plus the binary-shim ENV `WAKIR_RUST_ENGINE_BIN` (defined in
`rust_adapter_hook.py`) which addresses the persona-engine-real
binary path, not a per-component decision.

These three extras follow the same `WAKIR_*` canonical naming and
are documented in the spec v0.4.2 §4.1 catalogue. They are **not**
manifest §2 entries because manifest §2 enumerates the **boot
fan-out** flags, not every Rust-backend toggle in the codebase.

Legacy `WAKIR_PE_*_BACKEND` flags (superseded under v0.4.2 §5.6):
detected by `wirelang.persona_engine.legacy_env_migration_detector`
(Tag-51 Reza PR #329) with the warn-no-fallback posture. No
fallback path exists; setting a legacy flag emits a structured-log
warning and the unset canonical flag keeps its `python` default.

### 3.4 Dimension 4 — FSM State Diagram

**Verdict: MATCH.**

The Rust pendant `wirelang-rust/crates/persona-engine-fsm/src/lib.rs`
declares the closed enumeration of six lifecycle states:

| # | State | Wire String |
|---|---|---|
| 1 | `FsmState::Uninstantiated` | `"uninstantiated"` |
| 2 | `FsmState::Spawning` | `"spawning"` |
| 3 | `FsmState::Running` | `"running"` |
| 4 | `FsmState::Despawning` | `"despawning"` |
| 5 | `FsmState::Recovered` | `"recovered"` |
| 6 | `FsmState::Migrated` | `"migrated"` |

The `VALID_TRANSITIONS` constant declares exactly nine valid
edges:

| # | From | To | Lifecycle Role |
|---|---|---|---|
| 1 | uninstantiated | spawning | cold-start handshake |
| 2 | spawning | running | normal spawn success |
| 3 | spawning | uninstantiated | spawn-failure rollback |
| 4 | running | despawning | clean shutdown initiate |
| 5 | despawning | uninstantiated | clean shutdown finalise |
| 6 | uninstantiated | recovered | recovery-from-marker-stack |
| 7 | recovered | running | recovered-engine-resume |
| 8 | running | migrated | host/version boundary cross |
| 9 | migrated | uninstantiated | post-migration teardown |

The six-state + nine-transition shape matches spec
`wirelang/specs/persona-engine-format-spec.md` §3.3 row-for-row,
and matches the Python pendant
`wirelang.persona_engine.lifecycle_state_machine` `VALID_TRANSITIONS`
tuple. Cross-lang fixture file
`tests/fixtures/lifecycle-state-machine-cross-lang/fixtures.json`
resolves on-disk.

Error surface: three error variants
(`InvalidTransition`, `UnknownState`, `ReplayDrift`) match the
Python `InvalidTransitionError` + `UnknownStateError` + the
recovery-workflow audit-log-corruption marker. Type-state-pattern
discipline preserved.

### 3.5 Dimension 5 — V-907 Pin-Stability Substrate

**Verdict: MATCH-WITH-1-INTENTIONAL-DEFERRAL.**

The four V-907-substrate crates exist:

| Crate | Role | Version |
|---|---|---|
| `persona-hash` | V-907 hash primitive (`compute_persona_hash_from_canonical`) | 0.1.0 |
| `persona-canonical-form` | JCS-bytes boundary helper (axis-A subset) | 0.1.0 |
| `persona-canonical-form-yaml` | YAML front-matter parser → canonical subset | 0.1.0 |
| `persona-engine-v907-verify` | engine-side spawn-time verify gate | 0.1.0 |

`persona-engine-v907-verify` documents the SAMPLE_AXIS_A digest
pin:

```
sha256:cf66fbc5e02ebee97726d5903460e1c3b2b20d1e10db6db1083bceb62ede6e39
```

captured 2026-05-16 from a local Python run and anchored in
`tests/v907_verify_smoke_test.rs` (Tag-25 Zone-K Reza/Tomás
cross-reviewed).

The Tag-59 V-907 composite-hash seal at
`wirelang/persona_engine/v907-hash-baseline.json` declares:

```
composite_hash:
  a529d7d1b85ee33c61755cef7cb21793ff0ecf87d2efc5b9267f58526c818857
engine_version: 0.5.3-rc1
note: V-907 persona-hash-pin baseline for engine 0.5.3-rc1
      (Tag-58 PR #372). Sealed Tag-59. Refresh requires
      Selin-Hand + Tomas Zone-K cross-review.
```

The baseline still carries `engine_version: "0.5.3-rc1"` by design
— the §0 version-header (the only Tag-62 change) is outside the
V-907-bounded byte-range (manifest §1 + pin-pack
`boot_wired_crates` + engine.py resolver-block), so the composite
hash is mathematically unaffected by the rc1-suffix-drop. The
baseline file's `engine_version` and `note` fields are
documentation, not part of the hashed input.

The two-surface design (strict nine-vector pin pack
`PERSONA_HASH_PIN_V1..V9` in `persona-canonical-form-yaml` vs.
the lenient axis-A spawn-time verify shape in
`persona-engine-v907-verify`) is intentional and documented in
the crate-doc header. The strict nine-vector pin pack is the
hard-freeze identity-hash substrate (Tomás-Zone-K invariant);
the lenient axis-A shape is the spawn-time operator-pin-compare
substrate.

**Intentional deferral (Zone-K, OPEN-K3, not a defect):** the
baseline refresh from `0.5.3-rc1` to `0.5.3` requires Selin-Hand
+ Tomás-Zone-K cross-review per the Tag-59 seal contract. The
baseline file is the cross-review artefact; updating its
documentation metadata in-place would bypass the seal contract.
The release-notes §1 explicitly documents this as "the baseline
file still carries `0.5.3-rc1` in its `engine_version` and
`note` fields by design".

### 3.6 Dimension 6 — Containerfile.real Layer Integrity

**Verdict: MATCH-WITH-1-INTENTIONAL-CARRY-FORWARD.**

`infra/persona-engine/Containerfile.real` contains 21 layer
instructions (machine-counted: 1+7+7+3+1+1+1):

| Count | Instruction | Purpose |
|---|---|---|
| 1 | `FROM` | python:3.13-slim base image (digest pinning carry-forward — see OPEN-J3 below) |
| 7 | `LABEL` | OCI metadata (title, description, version, licenses, source, url, documentation) |
| 7 | `COPY` | pyproject + README + LICENSE + NOTICE + wirelang/ + wat/ + persona-engine-real binary shim |
| 3 | `RUN` | groupadd, pip install, chmod+symlink |
| 1 | `USER` | 1000:1000 (non-root) |
| 1 | `WORKDIR` | /opt/wakir-runtime |
| 1 | `ENTRYPOINT` | /opt/wakir/bin/persona-engine (symlinked to persona-engine-real) |

Image-version label is
`org.opencontainers.image.version="0.5.2-final-pre-cutover"`
(Tag-52-emitted, carry-forward; **not** refreshed to `0.5.3` by
Tag-62 — see OPEN-J3 below).

The entrypoint symlink chain
`/opt/wakir/bin/persona-engine -> /opt/wakir/bin/persona-engine-real`
is byte-stable across the stub-to-real swap. The Quadlet
`Exec=` line therefore does not move when operators rotate to a
new image tag — a deliberate Kai/Zone-J cross-review constraint
honoured here.

> **OPEN-J3 (Zone-J, intentional carry-forward, blocker-for-
> cutover-image-build):** The OCI `image.version` label still
> reads `0.5.2-final-pre-cutover`. The Tag-62 release-notes §1
> "Out of scope" list explicitly excludes
> "Containerfile-tag or compose-file change beyond what Kai
> coordinates separately (Zone-J)". The label refresh
> (`0.5.2-final-pre-cutover` → `0.5.3`) is a Kai-Hand action in
> the KW-24 cutover image-build pipeline. The 0.5.3 final
> release-substrate audit honours this scope split — Selin's
> domain ends at the engine wiring; Kai's domain begins at the
> Containerfile rebuild.

> **Closed (Tag-57 PR #366 by Tomás):** OPEN-K1 (Containerfile
> base-image SHA-256 digest pinning) and OPEN-K2 (OTS-anchor of
> the manifest hash via WAT spool). Both Tag-56 Zone-K items
> have been carry-forward-absorbed into the substrate; this
> Tag-63 audit does not re-open them.

> **Closed (Tag-57 PR #367 by Kai):** OPEN-J1 (Cross-Substrate-
> Parity-Gate green on PR). The Tag-56 Zone-J parity gate is
> live in CI; this Tag-63 audit does not re-open it.

### 3.7 Dimension 7 — Cargo Workspace Inventory

**Verdict: MATCH.**

`wirelang-rust/Cargo.toml` declares 32 workspace members (counted
by `"crates/<name>"` literals in the `members =` array).
Membership inventory:

| Bucket | Count | Members |
|---|---|---|
| Persona-foundation crates | 9 | `persona-hash`, `persona-canonical-form`, `persona-canonical-form-yaml`, `persona-migration`, `persona-migration-resolver`, `persona-cli`, `persona-validator`, `persona-converter`, `persona-pilot-export` |
| Persona-engine crates (pin-pack tracked) | 15 | All 15 from Dimension 2 |
| Persona-engine crates (auxiliary, not pin-pack tracked) | 8 | `persona-engine-format`, `persona-engine-smoke`, `persona-engine-nats-subjects`, `persona-engine-v907-recompute-bench`, `persona-engine-recovery-replay`, `persona-engine-loop-latency-bench`, `persona-engine-integration-tests`, `persona-engine-migrate-version` |

Note on the count: the Tag-56 audit reported 33 workspace members
based on the §7 dual-class counting prose; the live `Cargo.toml`
at main-tip `e74ea17` contains 32 distinct `"crates/<name>"`
literals, all on-disk-resolved. The Tag-56 prose's "33" total
counted `persona-engine-anchor-submit-worker` once-with-an-
asterisk in dual-class membership; the canonical
machine-readable count is 32 distinct workspace-member literals.
This Tag-63 audit reports the machine-readable count (32) as the
ground truth and supersedes the Tag-56 prose number; no
substrate change is involved — the workspace inventory is
byte-stable vs. Tag-52, Tag-58, and Tag-62.

The pinned dependency versions in the `[workspace.dependencies]`
block (`sha2 = "=0.10.8"`, `serde = "=1.0.219"`, `serde_json =
"=1.0.140"`, `serde_jcs = "=0.2.0"`, `serde_yaml = "=0.9.34"`,
`hex = "=0.4.3"`) are all strict-equality-pinned for byte-
reproducibility — a Phase-3a/3b parity gate prerequisite.

---

## 4. Production-Readiness Open-Item Tracker

| # | Item | Owner | Severity | Status | Closes Before |
|---|---|---|---|---|---|
| OPEN-J2 | Operator-Hand live-VM rotation `0.5.2`→`0.5.3` | Kai (Zone-J) / Operator-Hand | blocker-for-cutover | open | KW-24 cutover-T0 (2026-06-08/09) |
| OPEN-J3 | Containerfile.real OCI `image.version` label refresh `0.5.2-final-pre-cutover` → `0.5.3` | Kai (Zone-J) | blocker-for-cutover-image-build | intentional-carry-forward | KW-24 cutover-image-build |
| OPEN-K3 | V-907 composite-hash baseline `engine_version` documentation refresh `0.5.3-rc1` → `0.5.3` | Selin + Tomás (Zone-K cross-review) | non-blocking-documentation | intentional-by-design | KW-24 cutover-T0 or later (cross-review window) |
| INFO | Manifest-§6 cutover-window-open signal | Mira / AR / Operator-Hand | informational | open | KW-24 |

| Closed (since Tag-56) | Item | Closed by |
|---|---|---|
| OPEN-K1 (Tag-56) | Containerfile base-image SHA digest | Tomás Tag-57 PR #366 |
| OPEN-K2 (Tag-56) | OTS-anchor of manifest hash via WAT spool | Tomás Tag-57 PR #366 |
| OPEN-J1 (Tag-56) | Cross-substrate-parity-gate green on PR | Kai Tag-57 PR #367 |

All four open items (OPEN-J2, OPEN-J3, OPEN-K3, INFO) are
**non-Selin gates** — they surface here so the AR has a single-
pane view of remaining pre-cutover work. The `0.5.3` engine
release substrate itself is production-ready under Selin's
authority.

---

## 5. Hermetic Test Surface (Tag-63 Audit-Companion)

The hermetic test module
`wirelang/tests/persona_engine/test_tag63_production_readiness_audit.py`
encodes every numeric and string assertion in §3 as an executable
test. The module is structured per-dimension with one test class
per dimension (D1..D7) plus cross-cutting sanity tests, for a
total of **18 hermetic tests** (≥15 required by the dispatch):

| Dimension | Test Class | Test Count |
|---|---|---|
| D1 | `Test10BackendDecisions` | 3 |
| D2 | `Test15CratePinPack` | 2 |
| D3 | `TestEnvFlagConsistency` | 2 |
| D4 | `TestFsmStateDiagram` | 2 |
| D5 | `TestV907PinStability` | 3 |
| D6 | `TestContainerfileLayers` | 2 |
| D7 | `TestCargoWorkspace` | 2 |
| Cross-cutting | audit-report + 0.5.3-version-anchor + Tag-57-carry-forward-evidence | 2 |
| **Total** | | **18** |

100% hermetic: pytest-only, no network, no subprocess, no Rust
build, no engine boot. Verified green on main-tip `e74ea17` at
audit-creation time.

---

## 6. Cross-Substrate Reference Matrix

| Claim in 0.5.3-final substrate | Pin-pack YAML witness | Python-source witness | Rust-crate witness |
|---|---|---|---|
| 10 BackendDecision records | `boot_wired_crates[]` length=10 | `engine.py` 10 resolver call-sites | 10 wired crates in `crates/` |
| 15-crate pin pack | wired+unwired=15 | n/a | 15 Cargo.toml files |
| Selector ENV naming `WAKIR_*_BACKEND` | YAML `selector_env` keys | `rust_backend_switch.py` constants | n/a |
| Binary-path ENV naming `WAKIR_RUST_*_BIN` | YAML `binary_env` keys | `rust_backend_switch.py` constants | n/a |
| Cross-backend timeout `WAKIR_RUST_BACKEND_TIMEOUT_S` | `cross_backend.timeout_env` | `rust_backend_switch.py` | n/a |
| 6 FSM states, 9 transitions | n/a | `lifecycle_state_machine.py` | `persona-engine-fsm/src/lib.rs` |
| V-907 ground-truth SAMPLE_AXIS_A digest | n/a | `v907_verify.py` | `persona-engine-v907-verify/src/lib.rs` |
| V-907 composite-hash seal | n/a | `v907-hash-baseline.json` | n/a |
| Containerfile image tag (carry-forward) `0.5.2-final-pre-cutover` | `invariants.containerfile_image_tag` | n/a | n/a (image-side) |
| Engine version literal `0.5.3` | n/a | `__version__.py`, `engine_async.py`, `cli.py` docstring, `engine.py` import-comment | n/a |
| Byte-stable vs. `0.5.3-rc1` and `0.5.2-final-pre-cutover` | `invariants.byte_stable_versus` | n/a | All crates pinned 0.1.0 (no bump) |
| Tag-51 resilience contract (36 tests) pinned by reference | `resilience_contract.pinned_test_count` | `test_tag51_10_decision_engine_resilience.py` | n/a |
| Tag-57 emit-order pin (state_backing pre-boot) | n/a | `test_state_backing_pre_boot_emit_order_tag57.py` | n/a |
| Tag-58 0.5.3-rc1 release-notes | n/a | `docs/persona-engine/0-5-3-rc1-release-notes.md` | n/a |
| Tag-59 V-907 hash-pin baseline | n/a | `v907-hash-baseline.json` | n/a |
| Tag-61 G5-PRE-CUTOVER-READY compositum | n/a | `test_engine_pre_cutover_final_composite_tag61.py` | n/a |
| Tag-62 0.5.3-final-bump | n/a | `__version__.py = "0.5.3"`, release-notes, manifest §0 | n/a |

All sixteen cross-substrate witnesses agree at main-tip `e74ea17`.

---

## 7. ADR Anchors

The audit referenced and respected the following ADRs without
modification:

- **ADR-0036** — Self-Migration-Konverter; 0.5.3-rc1 → 0.5.3 is
  a no-op migration (metadata-only rc1-suffix-drop).
- **ADR-0043** — Selin Persona-Engine-Engineer activation; this
  audit is in Selin's domain.
- **ADR-0065** — SVID-Workload-Identity wire-in (Welle 2);
  Dimension 1 record #8.
- **ADR-0066** — Federation-Resolver wire-in (Welle 6);
  Dimension 1 record #9.
- **ADR-0023a** — Inter-Agent-Protokoll layer architecture;
  Wirelang Spec v0.4.2 cross-reference in Dimension 3.
- **ADR-0035 Errata-1** — Phase-1 bootstrap Python + Phase-1c
  Rust pendant; Dimension 7 dual-tree justification.
- **ADR-0025** — Performance-Mess-Anker (Antwort-Disziplin);
  this audit produced under continuous-mode, AR-persistent.

No ADR-erratum is recommended. The `0.5.3` release substrate is
byte-consistent with every cited ADR.

---

## 8. Conclusions

The `0.5.3` final persona-engine release substrate is
**PRODUCTION-READY-WITH-OPEN** within Selin's domain (Persona-
Engine).

- The 10-BackendDecision boot fan-out is byte-stable, fully
  wired, and triply-witnessed (manifest §1, pin-pack
  `boot_wired_crates`, engine.py source).
- The 15-crate cross-language pin pack is internally consistent,
  on-disk-resolved, and version-byte-stable vs. 0.5.3-rc1 and vs.
  0.5.2-final-pre-cutover.
- ENV-flag naming follows the canonical `WAKIR_*_BACKEND`
  convention with zero `_PE_` infix in the wired surface; legacy
  detection is in place with the warn-no-fallback posture.
- The FSM state diagram (6 states + 9 transitions) matches the
  spec and Python pendant row-for-row.
- The V-907 pin substrate (4 crates) is anchored on the
  SAMPLE_AXIS_A ground-truth digest captured 2026-05-16; the
  Tag-59 composite-hash seal is unchanged.
- The Containerfile.real has 21 layer instructions (1+7+7+3+
  1+1+1), the carry-forward image-tag label, and the entrypoint-
  symlink invariant honoured.
- The Cargo workspace has 32 members, all on-disk-resolved, all
  pinned-dependency-equality-versioned for byte-reproducibility.

The four open items (OPEN-J2/J3/K3/INFO) are cross-team
dependencies (Zone-J Kai-container, Zone-K Tomás-WAT, AR signal),
not engine defects. They close in the KW-24 cutover-window
preparation sequence, not in the `0.5.3` release substrate
itself.

The `0.5.3` final marker is the right release-tag for the KW-24
cutover gate to hash. The Tag-61 G5-PRE-CUTOVER-READY compositum
verdict (PR #391) authorised the rc1 → final promotion; this
Tag-63 audit confirms the final substrate is byte-consistent
with that authorisation.

— Selin Çelik, Persona-Engine-Engineer, Tag-63 Production-
Readiness Audit (Post-Final-Bump), 2026-05-19.
