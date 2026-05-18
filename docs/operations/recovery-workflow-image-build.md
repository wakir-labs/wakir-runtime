<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# `wakir-persona-engine-recovery` Image-Build (Recovery-Workflow)

**Status:** Living operations document.
**Scope:** Build, sign and publish the
`wakir-persona-engine-recovery` Rust-CLI container image (Welle-7
`recovery_workflow` cutover substrate).
**ADR anchor:** ADR-0066 §Phase-3c Welle-7 `recovery_workflow`
(approved 2026-05-17). Tag-33 Mini-Welle.
**Sibling docs:**
- `docs/operations/v907-verify-image-build.md` (Welle-1).
- `docs/operations/svid-workload-identity-image-build.md` (Welle-2).
- `docs/operations/bridge-audit-writer-image-build.md` (Welle-3).
- `docs/operations/state-backing-image-build.md` (Welle-4 sibling).
- `docs/operations/lifecycle-state-machine-image-build.md` (Welle-5
  sibling).
- `docs/operations/subscribe-loop-image-build.md` (Welle-6 sibling).
- `docs/operations/cosign-policy-phase-3b.md` (13-binary inventory
  now includes this image as `recovery-welle7`).

---

## 1. Why this image exists

ADR-0066 (approved 2026-05-17) accelerates Phase-3c to 4 weeks. The
Tag-33 Mini-Welle ships the **Welle-7 image-build** substrate: a
dedicated single-binary Rust-CLI container image for the persona-
engine R1..R4 recovery-workflow operator surface
(persona-engine-format-spec §3.7.4).

The Welle-7 cutover step (the final Welle in the ADR-0066 Phase-3c
sequence) will pin this image in a dedicated Quadlet, flip the
`WAKIR_RECOVERY_BACKEND=rust` operator flag and migrate the
production-default backend from Python
(`wirelang.persona_engine.recovery_workflow`) to the Rust pendant
in the `persona-engine-recovery` crate.

---

## 2. Subcommand surface

The binary lives at `/usr/local/bin/wakir-persona-engine-recovery`
inside the image. Two payload subcommands plus the standard
`--help` / `--version` surface:

```text
usage:
    wakir-persona-engine-recovery info
    wakir-persona-engine-recovery soft-cap PHASE
    wakir-persona-engine-recovery --version
    wakir-persona-engine-recovery --help
```

### 2.1 `info`

Prints the canonical R1..R4 recovery-workflow spec constants:

- `phase_order=R1,R2,R3,R4`
- `recovery_budget_seconds=30`
- Per-phase soft-cap seconds (`soft_cap_sec_R1`, `soft_cap_sec_R2`,
  `soft_cap_sec_R3`, `soft_cap_sec_R4`).
- `recovery_outcome_schema=wakir.persona-engine.recovery-outcome/1`
- `python_authority=wirelang.persona_engine.recovery_workflow`
- `version=<CARGO_PKG_VERSION>`

### 2.2 `soft-cap PHASE`

Looks up the soft-cap seconds for a given phase label (R1..R4)
using the library's `phase_soft_cap_sec` lookup. Exits 64 if the
phase label is unknown.

### 2.3 Exit codes

| Code | Meaning                                          |
|------|--------------------------------------------------|
| 0    | success: `info` / `soft-cap` / `--help` / `--version` |
| 1    | internal error (reserved for future I/O-bound subcommands) |
| 64   | usage error (unknown subcommand, missing argument, unknown phase label) |

---

## 3. Build pipeline

Build path: `.github/workflows/build-rust-cli-recovery-workflow.yml`.

Hybrid trigger (push-to-main dry-run + workflow_dispatch publish) —
parity with the prior six image-build workflows.

---

## 4. Operator-Hand publish recipe

```bash
gh workflow run build-rust-cli-recovery-workflow.yml \
    -f version_tag=0.1.0-pilot \
    -f push=true
```

---

## 5. Cross-references

- `wirelang-rust/crates/persona-engine-recovery/src/main.rs` —
  binary entry-point + unit-tests.
- `infra/recovery-workflow-rust-cli/Containerfile` — multi-stage
  build recipe.
- `tests/workflows/test_build_rust_cli_welle_4_5_6_7.py` —
  hermetic workflow-structure tests.
- `policies/cosign-policy-phase-3b.yaml` — 13-binary inventory
  including this image as `recovery-welle7`.
