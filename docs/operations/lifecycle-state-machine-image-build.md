<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# `wakir-persona-engine-fsm` Image-Build (Lifecycle State-Machine)

**Status:** Living operations document.
**Scope:** Build, sign and publish the
`wakir-persona-engine-fsm` Rust-CLI container image (Welle-5
`lifecycle_state_machine` cutover substrate).
**ADR anchor:** ADR-0066 §Phase-3c Welle-5
`lifecycle_state_machine` (approved 2026-05-17). Tag-33 Mini-Welle.
**Sibling docs:**
- `docs/operations/v907-verify-image-build.md` (Welle-1).
- `docs/operations/svid-workload-identity-image-build.md` (Welle-2).
- `docs/operations/bridge-audit-writer-image-build.md` (Welle-3).
- `docs/operations/state-backing-image-build.md` (Welle-4 sibling,
  same Tag-33 Mini-Welle).
- `docs/operations/subscribe-loop-image-build.md` (Welle-6 sibling,
  same Tag-33 Mini-Welle).
- `docs/operations/recovery-workflow-image-build.md` (Welle-7 sibling,
  same Tag-33 Mini-Welle).
- `docs/operations/cosign-policy-phase-3b.md` (13-binary inventory
  now includes this image as `fsm-welle5`).

---

## 1. Why this image exists

ADR-0066 (approved 2026-05-17) accelerates Phase-3c to 4 weeks. The
Tag-33 Mini-Welle ships the **Welle-5 image-build** substrate: a
dedicated single-binary Rust-CLI container image for the persona-
engine lifecycle state-machine operator surface
(persona-engine-format-spec §3.3, six states, nine transitions).

The Welle-5 cutover step will pin this image in a dedicated Quadlet,
flip the `WAKIR_FSM_BACKEND=rust` operator flag and migrate the
production-default backend from Python
(`wirelang.persona_engine.lifecycle_state_machine`) to the Rust
pendant in the `persona-engine-fsm` crate.

---

## 2. Subcommand surface

The binary lives at `/usr/local/bin/wakir-persona-engine-fsm`
inside the image. Two payload subcommands plus the standard
`--help` / `--version` surface:

```text
usage:
    wakir-persona-engine-fsm info
    wakir-persona-engine-fsm validate FROM TO
    wakir-persona-engine-fsm --version
    wakir-persona-engine-fsm --help
```

### 2.1 `info`

Prints all six lifecycle state wire-strings, all nine valid
transitions (as `transition_N=FROM->TO` lines), the canonical
lifecycle-trace schema string and the binary version.

The wire-strings (`uninstantiated | spawning | running |
despawning | recovered | migrated`) are the closed enumeration from
spec §3.3.

### 2.2 `validate FROM TO`

Exit 0 if `(FROM, TO)` is in the spec's `VALID_TRANSITIONS` list,
exit 3 if rejected (closed-enumeration violation), exit 64 on
unknown state wire-strings.

### 2.3 Exit codes

| Code | Meaning                                          |
|------|--------------------------------------------------|
| 0    | success: `info` / `validate` accepted / `--help` / `--version` |
| 1    | internal error (reserved for future I/O-bound subcommands) |
| 3    | `validate`: transition rejected (edge not in VALID_TRANSITIONS) |
| 64   | usage error (unknown subcommand, missing argument, unknown state wire-string) |

---

## 3. Build pipeline

Build path:
`.github/workflows/build-rust-cli-lifecycle-state-machine.yml`.

Hybrid trigger (push-to-main dry-run + workflow_dispatch publish) —
parity with the prior four image-build workflows.

---

## 4. Operator-Hand publish recipe

```bash
gh workflow run build-rust-cli-lifecycle-state-machine.yml \
    -f version_tag=0.1.0-pilot \
    -f push=true
```

---

## 5. Cross-references

- `wirelang-rust/crates/persona-engine-fsm/src/main.rs` — binary
  entry-point + unit-tests.
- `infra/lifecycle-state-machine-rust-cli/Containerfile` — multi-
  stage build recipe.
- `tests/workflows/test_build_rust_cli_welle_4_5_6_7.py` —
  hermetic workflow-structure tests.
- `policies/cosign-policy-phase-3b.yaml` — 13-binary inventory
  including this image as `fsm-welle5`.
