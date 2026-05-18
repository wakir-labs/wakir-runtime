<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# `wakir-persona-engine-state-backing` Image-Build

**Status:** Living operations document.
**Scope:** Build, sign and publish the
`wakir-persona-engine-state-backing` Rust-CLI container image.
**ADR anchor:** ADR-0066 §Phase-3c Welle-4 `state_backing`
(approved 2026-05-17). Tag-33 Mini-Welle.
**Sibling docs:**
- `docs/operations/v907-verify-image-build.md` (Welle-1).
- `docs/operations/svid-workload-identity-image-build.md` (Welle-2).
- `docs/operations/bridge-audit-writer-image-build.md` (Welle-3).
- `docs/operations/lifecycle-state-machine-image-build.md` (Welle-5
  sibling, same Tag-33 Mini-Welle).
- `docs/operations/subscribe-loop-image-build.md` (Welle-6 sibling,
  same Tag-33 Mini-Welle).
- `docs/operations/recovery-workflow-image-build.md` (Welle-7 sibling,
  same Tag-33 Mini-Welle).
- `docs/operations/cosign-policy-phase-3b.md` (the policy the image
  must satisfy; 13-binary inventory now includes this image as
  `state-backing-welle4`).

---

## 1. Why this image exists

ADR-0066 (approved 2026-05-17) accelerates Phase-3c to 4 weeks
(Option A+). The Tag-33 Mini-Welle ships the **Welle-4 image-build**
substrate: a dedicated single-binary Rust-CLI container image for the
persona-engine NATS-KV Persona-State-Backing operator surface.

The Welle-4 cutover step (a subsequent Mini-Welle) will pin this
image in a dedicated Quadlet, flip the
`WAKIR_STATE_BACKING_BACKEND=rust_inmemory|rust_natskv` operator
flag and migrate the production-default backend from Python
(`wirelang.persona_engine.state_backing`) to the Rust pendant in the
`persona-engine-state-backing` crate.

The library crate shipped earlier in Phase-3a; the Tag-33 image-build
adds the `[[bin]]` target + Containerfile + workflow + cosign-policy
entry that turns the library into a deployable container image.

---

## 2. Subcommand surface

The binary lives at `/usr/local/bin/wakir-persona-engine-state-backing`
inside the image. Two payload subcommands plus the standard
`--help` / `--version` surface:

```text
usage:
    wakir-persona-engine-state-backing info
    wakir-persona-engine-state-backing offset-key OFFSET
    wakir-persona-engine-state-backing --version
    wakir-persona-engine-state-backing --help
```

### 2.1 `info`

Prints the canonical NATS-KV key-prefix constants (one
`key=value` pair per line):

- `state_pack_key_prefix=state-pack`
- `offset_key_width=20`
- `pinned_key=state-pack/__pinned__`
- `next_offset_key=state-pack/__next_offset__`
- `latest_key=state-pack/latest`
- `python_authority=wirelang.persona_engine.state_backing`
- `version=<CARGO_PKG_VERSION>`

### 2.2 `offset-key OFFSET`

Renders the zero-padded NATS-KV key for a given non-negative
integer offset using the library's `offset_key(off)` formatter.
Byte-identical against the Python pendant
`wirelang.persona_engine.state_backing.offset_key()`.

### 2.3 Exit codes

| Code | Meaning                                          |
|------|--------------------------------------------------|
| 0    | success: `info` / `offset-key` / `--help` / `--version` |
| 1    | internal error (reserved for future I/O-bound subcommands) |
| 64   | usage error (unknown subcommand, missing argument, malformed integer) |

---

## 3. Build pipeline

Build path: `.github/workflows/build-rust-cli-state-backing.yml`.

The workflow runs in two modes per the hybrid-trigger posture from
the prior three image-builds:

- `push` to `main` under
  `wirelang-rust/crates/persona-engine-state-backing/**` — substrate-
  CI dry-run (no GHCR push, no Cosign sign).
- `workflow_dispatch` with `inputs.push='true'` — Operator-Hand
  publish flow that pushes the image to GHCR and Sigstore-keyless-
  signs the resulting digest against the GitHub-Actions OIDC
  identity.

---

## 4. Build artefacts

- Image: `ghcr.io/wakir-labs/wakir-persona-engine-state-backing:<tag>`
- Cosign signature: Sigstore-keyless via the workflow's
  `id-token: write` OIDC token (no static `cosign.pub`).
- Digest artefact: workflow upload
  (`wakir-persona-engine-state-backing-digest`) consumed by the
  Welle-4 cutover step.

---

## 5. Operator-Hand publish recipe

```bash
gh workflow run build-rust-cli-state-backing.yml \
    -f version_tag=0.1.0-pilot \
    -f push=true
```

The workflow's `Emit workflow summary` step prints the resulting
digest and the byte-precise sed-substitution recipe that the
Welle-4 cutover step will paste into the Welle-4 dedicated
Quadlet's image pin.

---

## 6. Cross-references

- `wirelang-rust/crates/persona-engine-state-backing/src/main.rs` —
  binary entry-point + unit-tests.
- `infra/state-backing-rust-cli/Containerfile` — multi-stage build
  recipe.
- `tests/workflows/test_build_rust_cli_welle_4_5_6_7.py` —
  hermetic workflow-structure tests (parametrised across all four
  Welle-4..7 workflows).
- `policies/cosign-policy-phase-3b.yaml` — 13-binary inventory
  including this image as `state-backing-welle4`.
