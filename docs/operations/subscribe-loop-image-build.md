<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# `wakir-persona-engine-subscribe-loop` Image-Build

**Status:** Living operations document.
**Scope:** Build, sign and publish the
`wakir-persona-engine-subscribe-loop` Rust-CLI container image
(Welle-6 `subscribe_loop` cutover substrate).
**ADR anchor:** ADR-0066 §Phase-3c Welle-6 `subscribe_loop`
(approved 2026-05-17). Tag-33 Mini-Welle.
**Sibling docs:**
- `docs/operations/v907-verify-image-build.md` (Welle-1).
- `docs/operations/svid-workload-identity-image-build.md` (Welle-2).
- `docs/operations/bridge-audit-writer-image-build.md` (Welle-3).
- `docs/operations/state-backing-image-build.md` (Welle-4 sibling).
- `docs/operations/lifecycle-state-machine-image-build.md` (Welle-5
  sibling).
- `docs/operations/recovery-workflow-image-build.md` (Welle-7 sibling,
  same Tag-33 Mini-Welle).
- `docs/operations/cosign-policy-phase-3b.md` (13-binary inventory
  now includes this image as `subscribe-loop-welle6`).

---

## 1. Why this image exists

ADR-0066 (approved 2026-05-17) accelerates Phase-3c to 4 weeks. The
Tag-33 Mini-Welle ships the **Welle-6 image-build** substrate: a
dedicated single-binary Rust-CLI container image for the persona-
engine NATS-JetStream subscribe-loop operator surface.

The Welle-6 cutover step will pin this image in a dedicated
Quadlet, flip the `WAKIR_SUBSCRIBE_LOOP_BACKEND=rust` operator flag
and migrate the production-default backend from Python
(`wirelang.persona_engine.subscribe_loop`) to the Rust pendant in
the `persona-engine-subscribe-loop` crate.

Note: a `subscribe-loop` binary already shipped in the carrier
image earlier (Tag-22 Mini-Welle PR #181 wired the Python
production-default switch). The Tag-33 image-build adds the
**dedicated single-binary image** for the Welle-6 cutover step —
the cutover Quadlet pins a single-binary image so a rollback flips
the `WAKIR_SUBSCRIBE_LOOP_BACKEND` flag back to Python without
touching the carrier-image digest.

---

## 2. Subcommand surface

The binary lives at `/usr/local/bin/wakir-persona-engine-subscribe-loop`
inside the image. Two payload subcommands plus the standard
`--help` / `--version` surface:

```text
usage:
    wakir-persona-engine-subscribe-loop info
    wakir-persona-engine-subscribe-loop build-subject ENV PERSONA_SLUG
    wakir-persona-engine-subscribe-loop --version
    wakir-persona-engine-subscribe-loop --help
```

### 2.1 `info`

Prints the canonical NATS-JetStream subscribe-loop schema constants:

- `accepted_inbound_schema=wakir.agent.task-assigned/1`
- `outbound_output_schema=wakir.agent.task-output/1`
- `ack_record_schema=wakir.persona-engine.subscribe-ack/1`
- `subject_template=wakir.{env}.agent.agent.task.assigned.{persona_slug}`
- The five valid outcome strings (`processed`, `malformed`,
  `persona_mismatch`, `rejected`, `empty_payload`).
- `python_authority=wirelang.persona_engine.subscribe_loop`
- `version=<CARGO_PKG_VERSION>`

### 2.2 `build-subject ENV PERSONA_SLUG`

Renders the NATS-JetStream subject string for a given (env,
persona-slug) pair using the library's `build_subscribe_subject`
formatter. The output is byte-identical to the Python pendant
`wirelang.persona_engine.subscribe_loop.build_subscribe_subject`
for the same arguments.

Validation: `env` must be one of `dev/staging/prod`,
`persona_slug` must match `[a-z][a-z0-9_-]*`.

### 2.3 Exit codes

| Code | Meaning                                          |
|------|--------------------------------------------------|
| 0    | success: `info` / `build-subject` / `--help` / `--version` |
| 1    | internal error (reserved for future I/O-bound subcommands) |
| 64   | usage error (unknown subcommand, missing argument, malformed env / persona-slug) |

---

## 3. Build pipeline

Build path: `.github/workflows/build-rust-cli-subscribe-loop.yml`.

Hybrid trigger (push-to-main dry-run + workflow_dispatch publish) —
parity with the prior five image-build workflows.

---

## 4. Operator-Hand publish recipe

```bash
gh workflow run build-rust-cli-subscribe-loop.yml \
    -f version_tag=0.1.0-pilot \
    -f push=true
```

---

## 5. Cross-references

- `wirelang-rust/crates/persona-engine-subscribe-loop/src/main.rs` —
  binary entry-point + unit-tests.
- `infra/subscribe-loop-rust-cli/Containerfile` — multi-stage build
  recipe.
- `tests/workflows/test_build_rust_cli_welle_4_5_6_7.py` —
  hermetic workflow-structure tests.
- `policies/cosign-policy-phase-3b.yaml` — 13-binary inventory
  including this image as `subscribe-loop-welle6`.
