<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# wakir-persona-engine-state-backing image build

Operator runbook for the persona-engine NATS-KV state-backing
Rust-CLI container image (Tag-32 Mini-Welle, ADR-0066 Welle-4
pre-cutover image, parallel to ADR-0066 Welle-1 V907-verify
(PR #194) and Welle-2 SVID-workload-identity (PR #201)).

> **Status (2026-05-17):** image-build pipeline + Rust-CLI binary
> ship in Tag-32; the binary surface is read-only utility (info,
> snapshot-hash, offset-key). The live NATS-KV socket binding stays
> Python-side during Phase-3a; this image substrates the Welle-4
> cutover (KW 26) by exposing the deterministic digest +
> canonical-key helpers.

---

## 1. Scope

This document covers operator-hand publication of the
`wakir-persona-engine-state-backing` container image and the
Welle-4 cutover-pin propagation.

### Binary surface

```
wakir-persona-engine-state-backing info
wakir-persona-engine-state-backing snapshot-hash <persona-id> <jcs-file>
wakir-persona-engine-state-backing offset-key <offset>
wakir-persona-engine-state-backing --version
wakir-persona-engine-state-backing --help
```

**Exit codes** (CLI contract):

| Code | Meaning |
|---|---|
| 0  | success |
| 1  | runtime error (parse / hash / IO) |
| 3  | input file not found |
| 64 | usage error |

---

## 2. Build path

### 2.1 Substrate-CI lane (push-to-main)

On push to `main` with changes under any of:

- `wirelang-rust/crates/persona-engine-state-backing/**`
- `infra/state-backing-rust-cli/Containerfile`
- `.github/workflows/build-rust-cli-state-backing.yml`

the substrate-CI workflow runs cargo build + `--help` + `--version`
smoke, skopeo + crane base-layer cross-check, in-runner sed
substitution of `DIGEST_PENDING_KAI_REVIEW` placeholders, and
`buildah bud` against the runner-local Containerfile. **Image is
NOT pushed** on this lane.

### 2.2 Publish lane (workflow_dispatch)

Operator-Hand opt-in: `workflow_dispatch` with `inputs.push='true'`.

```sh
gh workflow run build-rust-cli-state-backing.yml \
    -f version_tag=0.1.0-pilot \
    -f push=true \
    --ref main
```

The workflow then performs the substrate-CI steps PLUS buildah push
to `ghcr.io/wakir-labs/wakir-persona-engine-state-backing:<tag>`,
Sigstore-keyless sign against the GitHub-Actions OIDC identity, and
digest-artefact emission.

`version_tag` is fenced against the regex
`^[0-9]+\.[0-9]+\.[0-9]+-pilot$` (Sprint-Pengine-13 pattern).

---

## 3. Pin propagation

After Operator-Hand publication, the digest emitted in the
workflow's digest artefact is propagated into:

1. `policies/cosign-policy-phase-3b.yaml`
   `standalone_images[name='state-backing'].expected_image_digest`.
2. The Welle-4 cutover-PR's Quadlet pin (Welle-4 standalone-image
   Quadlet — to be authored in the cutover-PR, not in this PR).
3. `quadlet/wakir-rust-cli.container` already references the binary
   via the carrier-image install path; the Welle-4 standalone-image
   pin lands when the cutover-PR ships the standalone-image-pinned
   sibling Quadlet.

The resolver pattern is the same
`scripts/image-pin-idempotent-resolver.sh` PINS-array row that the
persona-engine + V907-verify + SVID-workload-identity images use.

---

## 4. Verification

After publication, an operator can verify the image with cosign:

```sh
cosign verify \
    --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/wakir-labs/wakir-persona-engine-state-backing:0.1.0-pilot@<resolved-digest>
```

And smoke-test the binary inside the image:

```sh
podman run --rm \
    ghcr.io/wakir-labs/wakir-persona-engine-state-backing:0.1.0-pilot@<resolved-digest> \
    info
```

Expected output: operator-discovery banner with
`state_pack_key_prefix=state-pack`, `offset_key_width=20`, etc.

---

## 5. Cross-references

- ADR-0066 §Phase-3c Welle-4 `state_backing` (approved 2026-05-17).
- ADR-0063 §Folgeartefakte Phase-3a Item 6 (library crate authority).
- ADR-0060 — Cosign-Policy on Pilot-Container-Images.
- ADR-0035 §C-Drift-Closure — the ADR this cutover closes for the
  state_backing module.
- `policies/cosign-policy-phase-3b.yaml` §`standalone_images` — the
  cross-substrate-parity-aligned digest registry.
- `tests/workflows/test_build_rust_cli_welle_4_5_6_7.py` — hermetic
  workflow-structure invariants.

— Selin Çelik (Persona-Engine-Engineer)
