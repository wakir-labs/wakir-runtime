<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# wakir-persona-engine-lifecycle-state-machine image build

Operator runbook for the persona-engine lifecycle state-machine
Rust-CLI container image (Tag-32 Mini-Welle, ADR-0066 Welle-5
pre-cutover image, parallel to ADR-0066 Welle-4 state-backing).

> **Status (2026-05-17):** image-build pipeline + Rust-CLI binary
> ship in Tag-32; the binary surface is read-only utility (info,
> states, transitions, can, trace-hash). The wire-strings emitted
> by `states` + `transitions` are byte-identical to the Python
> `STATES` tuple + `VALID_TRANSITIONS` tuple per spec §3.3.

---

## 1. Scope

This document covers operator-hand publication of the
`wakir-persona-engine-lifecycle-state-machine` container image and
the Welle-5 cutover-pin propagation.

### Binary surface

```
wakir-persona-engine-lifecycle-state-machine info
wakir-persona-engine-lifecycle-state-machine states
wakir-persona-engine-lifecycle-state-machine transitions
wakir-persona-engine-lifecycle-state-machine can <from> <to>
wakir-persona-engine-lifecycle-state-machine trace-hash <jcs-file>
wakir-persona-engine-lifecycle-state-machine --version
wakir-persona-engine-lifecycle-state-machine --help
```

**Exit codes** (CLI contract):

| Code | Meaning |
|---|---|
| 0  | success (or `can` returns valid) |
| 1  | runtime error (parse / hash / IO) OR `can` returns invalid |
| 3  | input file not found |
| 64 | usage error or unknown state |

---

## 2. Build path

### 2.1 Substrate-CI lane (push-to-main)

On push to `main` with changes under any of:

- `wirelang-rust/crates/persona-engine-fsm/**`
- `infra/lifecycle-state-machine-rust-cli/Containerfile`
- `.github/workflows/build-rust-cli-lifecycle-state-machine.yml`

the substrate-CI workflow runs cargo build + smoke + base-layer
cross-check + Containerfile substitution + `buildah bud`. **Image
is NOT pushed** on this lane.

### 2.2 Publish lane (workflow_dispatch)

```sh
gh workflow run build-rust-cli-lifecycle-state-machine.yml \
    -f version_tag=0.1.0-pilot \
    -f push=true \
    --ref main
```

Publishes to
`ghcr.io/wakir-labs/wakir-persona-engine-lifecycle-state-machine:<tag>`
and Sigstore-keyless-signs against the GitHub-Actions OIDC identity.

`version_tag` is fenced against the regex
`^[0-9]+\.[0-9]+\.[0-9]+-pilot$`.

---

## 3. Pin propagation

After Operator-Hand publication:

1. Update `policies/cosign-policy-phase-3b.yaml`
   `standalone_images[name='lifecycle-state-machine'].expected_image_digest`.
2. Author the Welle-5 standalone-image Quadlet pin in the cutover-PR
   (KW 26).

---

## 4. Verification

```sh
cosign verify \
    --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/wakir-labs/wakir-persona-engine-lifecycle-state-machine:0.1.0-pilot@<resolved-digest>
```

Smoke-test:

```sh
podman run --rm \
    ghcr.io/wakir-labs/wakir-persona-engine-lifecycle-state-machine:0.1.0-pilot@<resolved-digest> \
    states
```

Expected output: six lifecycle-state wire-strings, one per line, in
spec order.

```sh
podman run --rm \
    ghcr.io/wakir-labs/wakir-persona-engine-lifecycle-state-machine:0.1.0-pilot@<resolved-digest> \
    transitions
```

Expected output: nine `from -> to` transition lines.

---

## 5. Cross-references

- ADR-0066 §Phase-3c Welle-5 `lifecycle_state_machine` (approved
  2026-05-17).
- persona-engine-format-spec §3.3 — six states, nine transitions
  (the contract this binary surfaces).
- ADR-0060 — Cosign-Policy on Pilot-Container-Images.
- ADR-0035 §C-Drift-Closure — the ADR this cutover closes for the
  lifecycle_state_machine module.
- `policies/cosign-policy-phase-3b.yaml` §`standalone_images`.
- `tests/workflows/test_build_rust_cli_welle_4_5_6_7.py`.

— Selin Çelik (Persona-Engine-Engineer)
