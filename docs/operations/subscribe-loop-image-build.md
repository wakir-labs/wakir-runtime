<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# wakir-persona-engine-subscribe-loop image build

Operator runbook for the persona-engine NATS-JetStream subscribe-
loop Rust-CLI container image (Tag-32 Mini-Welle, ADR-0066 Welle-6
pre-cutover image, parallel to ADR-0066 Welle-7 recovery-workflow).

> **Status (2026-05-17):** image-build pipeline + Rust-CLI binary
> ship in Tag-32; the binary surface is read-only utility (info,
> subject canonicalisation, ack-hash). The live NATS connection
> binding stays Python-side during Phase-3a.

---

## 1. Scope

This document covers operator-hand publication of the
`wakir-persona-engine-subscribe-loop` container image and the
Welle-6 cutover-pin propagation.

### Binary surface

```
wakir-persona-engine-subscribe-loop info
wakir-persona-engine-subscribe-loop subject <env> <persona-slug>
wakir-persona-engine-subscribe-loop ack-hash <jcs-file>
wakir-persona-engine-subscribe-loop --version
wakir-persona-engine-subscribe-loop --help
```

**Exit codes** (CLI contract):

| Code | Meaning |
|---|---|
| 0  | success |
| 1  | runtime error (parse / hash / IO) |
| 3  | input file not found |
| 64 | usage error or env / persona-slug validation failure |

`<env>` must be one of `dev`/`staging`/`prod`; `<persona-slug>` must
match `[a-z][a-z0-9_-]*` (parity with the Python
`build_subscribe_subject`).

---

## 2. Build path

### 2.1 Substrate-CI lane (push-to-main)

On push to `main` with changes under any of:

- `wirelang-rust/crates/persona-engine-subscribe-loop/**`
- `infra/subscribe-loop-rust-cli/Containerfile`
- `.github/workflows/build-rust-cli-subscribe-loop.yml`

the substrate-CI workflow runs cargo build + smoke + base-layer
cross-check + Containerfile substitution + `buildah bud`. **Image
is NOT pushed** on this lane.

### 2.2 Publish lane (workflow_dispatch)

```sh
gh workflow run build-rust-cli-subscribe-loop.yml \
    -f version_tag=0.1.0-pilot \
    -f push=true \
    --ref main
```

Publishes to
`ghcr.io/wakir-labs/wakir-persona-engine-subscribe-loop:<tag>` and
Sigstore-keyless-signs against the GitHub-Actions OIDC identity.

---

## 3. Pin propagation

After Operator-Hand publication:

1. Update `policies/cosign-policy-phase-3b.yaml`
   `standalone_images[name='subscribe-loop'].expected_image_digest`.
2. Author the Welle-6 standalone-image Quadlet pin in the cutover-PR
   (KW 27).

---

## 4. Verification

```sh
cosign verify \
    --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/wakir-labs/wakir-persona-engine-subscribe-loop:0.1.0-pilot@<resolved-digest>
```

Smoke-test:

```sh
podman run --rm \
    ghcr.io/wakir-labs/wakir-persona-engine-subscribe-loop:0.1.0-pilot@<resolved-digest> \
    subject dev selin
```

Expected output:
`wakir.dev.agent.agent.task.assigned.selin`.

---

## 5. Cross-references

- ADR-0066 §Phase-3c Welle-6 `subscribe_loop` (approved 2026-05-17).
- Selin PR #79 (Sprint-Pengine-13 Bug-42 fix) — Python schema
  authority.
- ADR-0060 — Cosign-Policy on Pilot-Container-Images.
- ADR-0035 §C-Drift-Closure — the ADR this cutover closes for the
  subscribe_loop module.
- `policies/cosign-policy-phase-3b.yaml` §`standalone_images`.
- `tests/workflows/test_build_rust_cli_welle_4_5_6_7.py`.

— Selin Çelik (Persona-Engine-Engineer)
