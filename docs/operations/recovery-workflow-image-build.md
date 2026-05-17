<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# wakir-persona-engine-recovery-workflow image build

Operator runbook for the persona-engine R1..R4 Recovery-Workflow
Rust-CLI container image (Tag-32 Mini-Welle, ADR-0066 Welle-7
pre-cutover image, parallel to ADR-0066 Welle-6 subscribe-loop).

> **Status (2026-05-17):** image-build pipeline + Rust-CLI binary
> ship in Tag-32; the binary surface is read-only utility (info,
> phases, soft-cap, outcome-hash). The live container-supervisor
> orchestration stays Python-side during Phase-3a; this image
> substrates the Welle-7 cutover (KW 27) by exposing the
> deterministic canonical-constants + outcome-digest helpers.

---

## 1. Scope

This document covers operator-hand publication of the
`wakir-persona-engine-recovery-workflow` container image and the
Welle-7 cutover-pin propagation.

### Binary surface

```
wakir-persona-engine-recovery-workflow info
wakir-persona-engine-recovery-workflow phases
wakir-persona-engine-recovery-workflow soft-cap <phase>
wakir-persona-engine-recovery-workflow outcome-hash <jcs-file>
wakir-persona-engine-recovery-workflow --version
wakir-persona-engine-recovery-workflow --help
```

**Exit codes** (CLI contract):

| Code | Meaning |
|---|---|
| 0  | success |
| 1  | runtime error (parse / hash / IO) |
| 3  | input file not found |
| 64 | usage error or unknown phase label |

Valid `<phase>` labels: `R1`, `R2`, `R3`, `R4` (per spec §3.7.4.2).

---

## 2. Build path

### 2.1 Substrate-CI lane (push-to-main)

On push to `main` with changes under any of:

- `wirelang-rust/crates/persona-engine-recovery/**`
- `infra/recovery-workflow-rust-cli/Containerfile`
- `.github/workflows/build-rust-cli-recovery-workflow.yml`

the substrate-CI workflow runs cargo build + smoke + base-layer
cross-check + Containerfile substitution + `buildah bud`. **Image
is NOT pushed** on this lane.

### 2.2 Publish lane (workflow_dispatch)

```sh
gh workflow run build-rust-cli-recovery-workflow.yml \
    -f version_tag=0.1.0-pilot \
    -f push=true \
    --ref main
```

Publishes to
`ghcr.io/wakir-labs/wakir-persona-engine-recovery-workflow:<tag>`
and Sigstore-keyless-signs against the GitHub-Actions OIDC identity.

---

## 3. Pin propagation

After Operator-Hand publication:

1. Update `policies/cosign-policy-phase-3b.yaml`
   `standalone_images[name='recovery-workflow'].expected_image_digest`.
2. Author the Welle-7 standalone-image Quadlet pin in the cutover-PR
   (KW 27).

---

## 4. Verification

```sh
cosign verify \
    --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/wakir-labs/wakir-persona-engine-recovery-workflow:0.1.0-pilot@<resolved-digest>
```

Smoke-test:

```sh
podman run --rm \
    ghcr.io/wakir-labs/wakir-persona-engine-recovery-workflow:0.1.0-pilot@<resolved-digest> \
    phases
```

Expected output: four lines `R1`, `R2`, `R3`, `R4`.

```sh
podman run --rm \
    ghcr.io/wakir-labs/wakir-persona-engine-recovery-workflow:0.1.0-pilot@<resolved-digest> \
    soft-cap R2
```

Expected output: `15` (per `PHASE_SOFT_CAPS_SEC["R2"] = 15`).

---

## 5. Cross-references

- ADR-0066 §Phase-3c Welle-7 `recovery_workflow` (approved
  2026-05-17).
- persona-engine-format-spec §3.7.4 — R1..R4 phase contract.
- ADR-0060 — Cosign-Policy on Pilot-Container-Images.
- ADR-0035 §C-Drift-Closure — the ADR this cutover closes for the
  recovery_workflow module.
- `policies/cosign-policy-phase-3b.yaml` §`standalone_images`.
- `tests/workflows/test_build_rust_cli_welle_4_5_6_7.py`.

— Selin Çelik (Persona-Engine-Engineer)
