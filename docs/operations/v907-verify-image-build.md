# V-907 Verify Rust-CLI — Container-Image-Build-Pipeline

**Scope:** Operator-recipe for building, signing and pushing the
`wakir-v907-verify` container image (`ghcr.io/wakir-labs/wakir-v907-verify:<tag>`).

**Tag-26 Mini-Welle, ADR-0065 Welle-1 pre-cutover image. Owner: Kai
Hoffmann (Dev-Engineering-3 / DevOps).**

## 1. What this image is

`wakir-v907-verify` is the Rust-CLI runtime image for the V-907
engine-side pin-compute + verify path. It packages the
`wakir-v907-verify` binary from the
`wirelang-rust/crates/persona-engine-v907-verify/` workspace member
into a multi-stage distroless container (rust:1.85-slim-bookworm
builder → gcr.io/distroless/cc-debian12:nonroot runtime).

The binary itself is a thin operator-CLI shim over the library
crate's `compute_v907_pin` / `verify_v907_pin` API. Two subcommands:

```text
wakir-v907-verify compute <persona-file>
wakir-v907-verify verify  <persona-file> <expected-pin>
```

Exit-code mapping:

| Code | Meaning                                       |
|------|-----------------------------------------------|
| 0    | success (compute) or pin match (verify)       |
| 1    | pin drift (verify-only) or parse/hash failure |
| 3    | persona-file not found                        |
| 64   | argparse usage error                          |

## 2. ADR alignment

- **ADR-0065** approved 2026-05-17 — Phase-3c Cutover-Plan (Python-
  Default → Rust-Default). Welle-1 is `v907_verify`: lowest-blast-
  radius, read-only verify path, first to flip. This image is the
  substrate the Welle-1 cutover step pins against.
- **ADR-0063** approved 2026-05-16 — Persona-Engine-Sprach-Revision-
  Rust-Rewrite. The library crate this binary wraps is Phase-3a-
  Rust-Crate-Bundle Item 3.
- **ADR-0060** approved 2026-05-16 — Cosign-Policy on Pilot-
  Container-Images. This workflow inherits the policy: every
  published digest is Sigstore-keyless-signed against the GitHub-
  Actions OIDC identity.
- **ADR-0035 §C** Drift-Closure — the cutover this image enables
  is one of seven that close the §C-Drift-Closure-Item.

## 3. Build trigger surface

`.github/workflows/build-rust-cli-v907-verify.yml` ships with a
hybrid trigger:

### 3.1 Push-to-main (substrate-CI lane, dry-run only)

Runs automatically when any of these paths change on `main`:

- `wirelang-rust/crates/persona-engine-v907-verify/**`
- `infra/v907-verify-rust-cli/Containerfile`
- `.github/workflows/build-rust-cli-v907-verify.yml`

The push-to-main run executes `cargo build --release` + buildah
build to verify the substrate compiles, but it **does NOT push to
GHCR and does NOT Cosign-sign**. The image stays inside the runner
and is garbage-collected at job end. This catches build regressions
early without auto-publishing under the GitHub-Actions OIDC identity.

### 3.2 workflow_dispatch (Operator-Hand publish lane)

Triggered manually by an authorised maintainer:

```bash
# From a workstation with `gh auth login` configured:
gh workflow run build-rust-cli-v907-verify.yml \
  --ref main \
  -f version_tag=0.1.0-pilot \
  -f push=true
```

`inputs.version_tag` must match `^[0-9]+\.[0-9]+\.[0-9]+-pilot$`
(substrate-fence regex; refuses values like `v0.1.0` or `0.1.0`).

`inputs.push='true'` is required for the publish path — the default
`push='false'` keeps workflow_dispatch in dry-run mode (same as a
push-to-main run).

When `push='true'`, the workflow:

1. Builds the image with buildah.
2. Pushes `ghcr.io/wakir-labs/wakir-v907-verify:<tag>` to GHCR.
3. Sigstore-keyless-signs the resulting digest.
4. Emits the digest as a workflow output AND uploads a
   `wakir-v907-verify-digest` artefact (retention 90 days).
5. Writes a workflow-summary block with the Welle-1 cutover pin-
   substitution recipe.

## 4. Pre-publish checklist

Before clicking "Run workflow" with `push=true`:

- [ ] Phase-3c Trigger-Gates 1-7 all green (see
      `docs/operations/phase-3c-trigger-gates.md`).
- [ ] ADR-0065 status is `approved` (verify in
      `decisions/0065-phase-3c-cutover-python-default-zu-rust-default.md`
      frontmatter).
- [ ] V907-Verify-Crate smoke-test is green locally
      (`cargo test -p persona-engine-v907-verify`).
- [ ] Containerfile placeholders (`DIGEST_PENDING_KAI_REVIEW`) are
      still present (the workflow substitutes them in-runner;
      committing real digests breaks idempotency).
- [ ] No floating-tag drift in the Containerfile FROM lines (i.e.
      `rust:1.85-slim-bookworm` is still the workspace `rust-
      version`).
- [ ] Cosign-Policy on GHCR is enforcing for `wakir-v907-verify`
      (parity with `wakir-persona-engine`).

## 4.5 Substrate-path choice — parallel to PR #187 carrier image

The existing Quadlet
`quadlet/wakir-rust-cli.container` (PR #187, Tag-24 Mini-Welle)
installs the V-907 Verify binary as the seventh of a seven-binary
inventory shipped from the `wakir-persona-engine` carrier image.
That carrier-image path remains the production substrate for the
seven Phase-3b Rust-CLI binaries.

The image this workflow publishes (`wakir-v907-verify`) is a
**parallel substrate option** — a single-binary distroless image
that contains only the V-907 verify CLI. It is useful for:

- Welle-1 cutover **canary deployments** where the operator wants
  the smallest-possible attack surface for the V-907 verify path
  before flipping the cluster-wide default.
- Out-of-band V-907 verify smoke runs from a CI lane that does not
  want to pull the full persona-engine carrier image.
- Cosign-policy enforcement experiments where a separate digest is
  easier to audit than a shared carrier-image digest.

The PR #187 carrier-image path and this single-binary distroless
path are **not mutually exclusive**: the carrier image continues to
ship the binary at `/opt/wakir/bin/wakir-persona-engine-v907-verify`
(installed by `wakir-rust-cli.container`); the distroless image
ships the same binary at `/usr/local/bin/wakir-v907-verify` (as its
ENTRYPOINT). The two paths consume the same Rust source, the same
`cargo build --release`, and produce byte-identical V-907 pin output
for any axis-A markdown input.

A separate Quadlet (`quadlet/wakir-v907-verify.container`) for the
distroless image is **not added in this PR** — that artefact is a
Welle-1-cutover-PR item, gated on the Mira-Hand selection between
"carrier-image-only" vs. "distroless-canary-then-carrier" cutover
shapes. The image must exist (this PR) before that Quadlet can pin
it; the substrate-fence here is therefore additive-only.

## 5. Post-publish (Welle-1 cutover pin-step)

After the workflow publishes the image, the Welle-1 cutover step
(scheduled Monday morning per ADR-0065 §Verifikations-Plan)
resolves the pushed digest into the consuming Quadlet pin:

```bash
# Pull the digest from the workflow artefact:
gh run download <run-id> -n wakir-v907-verify-digest -D /tmp/v907-digest
cat /tmp/v907-digest/wakir-v907-verify.digest
# Line 1: sha256:<64hex>  (full form)
# Line 2: <64hex>         (bare form)
```

Or, via the standard pin-resolver script:

```bash
scripts/image-pin-idempotent-resolver.sh --digest-source crane
```

The resolver script's PINS array carries (will carry, post-cutover)
a `wakir_v907_verify` row that consumes the digest and substitutes
the `quadlet/wakir-v907-verify.container` pin.

**Tomás Zone-C Cross-Review:** The Welle-1 cutover-PR that adds the
PINS row + the Quadlet unit + the ENV-flag default flip is a Zone-C
artefact (Container-Image-Pipeline × OTS-Anchoring). Tomás Matrix-
Lead reviews before merge per the ADR-0009 Zone-C contract.

## 6. Rollback procedure

If the V-907 verify Rust-backend shows a substanz-bug post-cutover
(per ADR-0065 §Rollback-Strategie):

1. **Operator-Hand-Decision** (Reza + Tomás Matrix-Lead).
2. Flip `WAKIR_ENGINE_V907_VERIFY_BACKEND=python` in the Quadlet
   unit (`quadlet/wakir-persona-tomas.container` `Environment=` line).
3. `systemctl --user restart wakir-persona-engine.service`.
4. Bridge-Audit-Writer-Konsistenz-Re-Verify (Selin).
5. The Rust image stays in GHCR (do not delete — Cosign-signed
   artefacts are write-once on the audit trail).
6. Postmortem per `decisions/strategy-postmortem-template.md`.

Rollback SLA: ≤10 minutes (verify path is stateless, no schema
migration).

## 7. Local cargo build (operator-hand, pre-flight)

The workflow runs the same `cargo build` step it would on a CI
runner, but operators can dry-run locally before triggering the
workflow:

```bash
cd /path/to/wakir-runtime/wirelang-rust
cargo build --release -p persona-engine-v907-verify --bin wakir-v907-verify
./target/release/wakir-v907-verify --version
# Should print: wakir-v907-verify 0.1.0
./target/release/wakir-v907-verify --help

# Smoke against a sample axis-A persona:
cat > /tmp/sample-axis-a.md << 'EOF'
---
name: tomas
description: Sample test persona for V-907 hashing
schema_version: persona-v1
identity_pinned:
  email: tomas@example.com
domain: dev-engineering
---

Body content here.
EOF
./target/release/wakir-v907-verify compute /tmp/sample-axis-a.md
# Should print:
# sha256:cf66fbc5e02ebee97726d5903460e1c3b2b20d1e10db6db1083bceb62ede6e39
# (Cross-language anchor pin captured 2026-05-16; mismatch indicates
# JCS-canonicalisation or YAML-front-matter drift.)
```

## 8. Sandbox boundary

This workflow runs on GitHub-Actions runners only. The
claude-dev-sandbox has no podman-socket access (per
`feedback_sandbox_host_trennung.md`) and therefore cannot run a
local buildah build. Operator-Hand maintainers running the workflow
manually are the only path to a published image.

The push-to-main lane is reachable from any PR-merge-to-main path,
but it is dry-run-only (no GHCR push, no Cosign signature). This
keeps the supply-chain provenance posture explicit: every published
artefact carries a workflow_dispatch event identity in its OIDC
claims.

## 9. Cross-references

- ADR-0065 (Phase-3c Cutover-Plan)
- ADR-0063 (Persona-Engine-Sprach-Revision)
- ADR-0060 (Live-FCOS-VM CI-Gate + Cosign-Policy)
- `docs/operations/phase-3c-cutover-runbook.md` (the Wochen-Plan
  this image feeds into)
- `docs/operations/phase-3c-trigger-gates.md` (the gate aggregator
  that must be green before Welle-1 starts)
- `docs/operations/cosign-policy-phase-3b.md` (the policy this
  image's signatures satisfy)
- `infra/v907-verify-rust-cli/Containerfile` (this image's source)
- `.github/workflows/build-rust-cli-v907-verify.yml` (this image's
  build workflow)
- `tests/workflows/test_build_rust_cli_v907_verify.py` (hermetic
  workflow-structure invariants)

---

_— Kai Hoffmann (Dev-Engineering-3 / DevOps), Tag-26 Mini-Welle, 2026-05-17._
