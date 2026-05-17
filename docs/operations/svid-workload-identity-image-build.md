<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# wakir-persona-engine-svid-workload-identity image build

Operator runbook for the SPIFFE Workload-API socket-presence probe
Rust-CLI container image (Tag-29 Mini-Welle, ADR-0066 Welle-2
pre-cutover image, parallel to ADR-0065 Welle-1 V907-verify image
from PR #194).

> **Status (2026-05-17):** image build pipeline + Rust crate skeleton
> ship in Tag-29; the full Workload-API gRPC `FetchX509SVID` RPC is
> intentionally deferred to a future Zone-L-reviewed crate revision
> (Tonic substrate larger than the probe surface). The probe + info
> subcommands are sufficient to flip the Welle-2 backend-decision
> from `binary_missing` to `binary_present`.

---

## 1. Scope

This document covers operator-hand publication of the
`wakir-persona-engine-svid-workload-identity` container image and
the Welle-2 cutover-pin propagation. The Rust-CLI binary inside the
image wraps the
`persona_engine_svid_workload_identity::probe_workload_api_socket`
library and is the substrate the Welle-2 cutover step in
`wirelang.persona_engine.rust_backend_switch` resolves to once
`WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND=rust` is set in operator
ENV.

### Binary surface

```
wakir-persona-engine-svid-workload-identity probe [--socket PATH]
wakir-persona-engine-svid-workload-identity info
wakir-persona-engine-svid-workload-identity --version
wakir-persona-engine-svid-workload-identity --help
```

**Exit codes** (CLI contract):

| Code | Subcommand | Meaning |
|---|---|---|
| 0   | `probe`             | socket reachable (`connect()` succeeded) |
| 0   | `info` / `--help` / `--version` | success |
| 1   | any                 | internal error |
| 2   | `probe`             | socket path missing on filesystem |
| 3   | `probe`             | socket present but `connect()` failed |
| 64  | any                 | usage error (unknown subcommand / bad argument) |

The Quadlet healthcheck and the cutover-step resolver consume the
exit code, **not stdout formatting**.

---

## 2. Build path

### 2.1 Substrate-CI lane (push-to-main)

On push to `main` with changes under any of:

- `wirelang-rust/crates/persona-engine-svid-workload-identity/**`
- `infra/svid-workload-identity-rust-cli/Containerfile`
- `.github/workflows/build-rust-cli-svid-workload-identity.yml`

the substrate-CI workflow runs:

1. `cargo build --release -p persona-engine-svid-workload-identity
   --bin wakir-persona-engine-svid-workload-identity` (substrate-CI
   smoke; catches main.rs regressions before the buildah stage).
2. `./target/release/wakir-persona-engine-svid-workload-identity
   --help` and `--version` smoke (catches argparse / version-string
   regressions).
3. skopeo + crane cross-check on the
   `rust:1.85-slim-bookworm` and
   `gcr.io/distroless/cc-debian12:nonroot` base-layer digests
   (refuses if the two registries disagree on the digest).
4. In-runner sed substitution of `DIGEST_PENDING_KAI_REVIEW`
   placeholders in
   `infra/svid-workload-identity-rust-cli/Containerfile` (NOT
   committed back to the repo).
5. `buildah bud` against the runner-local Containerfile. Image
   is **NOT pushed** on this lane; the runner-local image is
   discarded at job completion.

This lane is the **substrate-CI dry-run** posture. It is the
Sandbox-Trennung from `feedback_sandbox_host_trennung.md`:
GitHub-Actions runners are the only environment that can touch a
real registry; the dry-run path stays inside the runner.

### 2.2 Publish lane (workflow_dispatch)

Operator-Hand opt-in: `workflow_dispatch` with `inputs.push='true'`.

Operator runs:

```sh
gh workflow run build-rust-cli-svid-workload-identity.yml \
    -f version_tag=0.1.0-pilot \
    -f push=true \
    --ref main
```

The workflow then performs steps 1–5 above PLUS:

6. `buildah push
   ghcr.io/wakir-labs/wakir-persona-engine-svid-workload-identity:<tag>`.
7. Sigstore-keyless sign the resulting digest against the
   GitHub-Actions OIDC identity:
   `cosign sign --yes
   ghcr.io/wakir-labs/wakir-persona-engine-svid-workload-identity@<digest>`.
8. Emit a two-line digest artefact
   (`wakir-persona-engine-svid-workload-identity.digest`):
   line 1 is the full `sha256:<64hex>` form, line 2 is the bare
   64-hex (operator-convenience).

`version_tag` is fenced against the regex
`^[0-9]+\.[0-9]+\.[0-9]+-pilot$` — free-form values are rejected
with exit code 64. Parity with Tag-26 V907-verify (PR #194) and
Sprint-Pengine-13 substrate-fence pattern.

---

## 3. Welle-2 cutover pin substitution

After the publish lane returns a digest, propagate the digest into:

1. **Cosign-Policy:** `policies/cosign-policy-phase-3b.yaml`
   (the `binaries:` entry with `name: svid-workload-identity`).
   The pin substrate is the carrier image
   (`ghcr.io/wakir-labs/wakir-persona-engine`), not the stand-
   alone image, so the carrier-image digest slot is the one to
   update once the next persona-engine carrier image is rebuilt
   to include the new binary.
2. **Quadlet installer:** `quadlet/wakir-rust-cli.container`
   (`Image=ghcr.io/wakir-labs/wakir-persona-engine:<tag>@<digest>`).
3. **rust_backend_switch.py:** no code change needed — the resolver
   already records `binary_missing` as the precondition signal
   per Tag-25 PR #191; once the binary is present at
   `/opt/wakir/bin/wakir-persona-engine-svid-workload-identity`
   on the Pilot-VM, the resolver flips to `binary_present`.

The idempotent resolver pattern (Pfad B) is
`scripts/image-pin-idempotent-resolver.sh`. The byte-precise sed
equivalent is emitted in the workflow summary at publish time.

---

## 4. SPIRE-Agent socket contract

The Rust-CLI binary uses the default socket path
`/run/spire/agent-sockets/api.sock`, byte-identical to the Python
`DEFAULT_WORKLOAD_API_SOCKET_PATH` constant in
`wirelang/persona_engine/svid_workload_identity.py`.

The Quadlet bind-mount contract is the
`wakir-spire-agent-sockets.volume` named volume; the persona-engine
container mounts it at `/run/spire/agent-sockets`. For the Rust-
CLI binary to probe the socket, the same volume MUST be bind-
mounted into any container that invokes the binary — typically
this is already the case because the persona-engine image (the
carrier) carries both the Python authority and the Rust binary,
and both consume the same bind-mount.

Operator override: `--socket PATH` argument to the `probe`
subcommand. Mirrors the Python `WAKIR_SPIRE_WORKLOAD_API_SOCKET`
ENV-override semantics.

---

## 5. Sandbox boundary

This document and the workflow run on the GitHub-Actions
host-of-record. The hermetic test surface
(`tests/workflows/test_build_rust_cli_svid_workload_identity.py`)
parses the workflow YAML on disk only — no actions runner, no
GHCR egress, no cargo exec, no cosign exec — and is compatible
with the claude-dev sandbox.

**No sandbox process** calls cosign, crane, or skopeo against
ghcr.io per `feedback_sandbox_host_trennung.md`. Live publication
(`workflow_dispatch` with `push=true`) is Operator-Hand only.

---

## 6. Cross-references

- **ADR-0066** §Phase-3c Welle-2 `svid_workload_identity` —
  approved 2026-05-17, Option A+ 4-week acceleration.
- **ADR-0065** §Welle-2 listing — `svid_workload_identity`
  precondition closure via Selin's resolver PR #191; this PR
  ships the binary the resolver was recording `binary_missing`
  against.
- **ADR-0060** — Cosign-Policy on Pilot-Container-Images (the
  policy this image must satisfy at cutover time).
- **ADR-0035** §C-Drift-Closure — the ADR this cutover closes
  for the svid_workload_identity module.
- **PR #194** (Tag-26 Mini-Welle) — V907-verify Rust-CLI
  container-image-build-pipeline; this PR mirrors that pattern
  for the SVID-workload-identity module.
- **PR #191** (Tag-25 Mini-Welle, Selin) — Python-side resolver
  + `binary_missing` precondition record (the gap this crate
  closes).
- **`docs/operations/cosign-policy-phase-3b.md`** — Operator-Hand
  cosign-verify recipe for the carrier image (extended Tag-29
  to 8-binary inventory including svid-workload-identity).

— Kai
