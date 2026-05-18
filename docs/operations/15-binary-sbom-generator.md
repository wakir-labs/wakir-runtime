<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

# 15-Binary SBOM Generator — Operator Recipe (Tag-48, Kai)

This runbook accompanies
`scripts/observability/generate-15-binary-sbom.py` (Tag-48, Kai)
and the daily workflow at
`.github/workflows/15-binary-sbom-daily.yml`.

It tells an operator how to:

1. Read the SBOM bundle in the GitHub-Actions run summary.
2. Re-generate the bundle locally (stdlib-mode, hermetic).
3. Refresh the bundle against a fully-resolved Cargo build
   (operator-hand only, `cargo-cyclonedx` fall-back path).
4. Spot-check a per-binary SBOM against the cosign-policy
   inventory.

## 1. Context

The Phase-3a-Foundation 15-binary substrate is pinned across
three independent surfaces:

- `policies/cosign-policy-phase-3b.yaml` — the canonical
  15-binary cosign-policy inventory (Tag-45 PR #294).
- `quadlet/wakir-rust-cli.container` — the carrier-image
  installer (Tag-45 substrate refresh).
- `wirelang/specs/wirelang-spec-v0-4.md` §3.1 — the spec
  reference catalogue (Tag-45 PR #291).

Tag-46 PR #298 added the A6 substrate-layer coverage matrix (17
hermetic invariants) and Tag-47 PR #307 added the
Cosign-Keyless-OIDC-Drift-Probe (Sigstore Trust-Root time-axis).

What none of these captured is the per-binary dependency tree —
which third-party crate versions Cargo statically links into
each binary. **That is the gap this Tag-48 generator fills.**

When AR signs off a Welle (per ADR-0066 §AR-Hand-Gate), the
audit-trail bundle now includes:

- The cosign-verified image digest.
- The OIDC-drift-probe verdict for the day.
- **The 15-binary SBOM bundle (this Tag-48 deliverable).**

## 2. Reading the daily Job-Summary

The workflow runs at **07:00 UTC daily** and on every PR that
touches `Cargo.lock`, `Cargo.toml`, the policy YAML, or the
generator script itself.

In the GitHub-Actions UI:

1. Open the `15-binary-sbom-daily` workflow.
2. Pick the run dated `YYYY-MM-DD` matching the audit window.
3. Read the Job-Summary block — it lists all 15 binaries plus
   their transitive-dep count.
4. Download the `15-binary-sbom-${RUN_ID}` artefact (30-day
   retention) for the raw CycloneDX-1.5 JSON files.

The artefact contains:

```text
out/sbom/
├── anchor-emitter.cdx.json
├── bridge-audit-replay.cdx.json
├── bridge-audit-writer.cdx.json
├── bridge-diff.cdx.json
├── envelope.json
├── fsm.cdx.json
├── fsm-welle5.cdx.json
├── metrics.prom
├── migrate-version.cdx.json
├── recovery.cdx.json
├── recovery-welle7.cdx.json
├── state-backing.cdx.json
├── state-backing-welle4.cdx.json
├── subscribe-loop.cdx.json
├── subscribe-loop-welle6.cdx.json
├── summary.md
├── svid-workload-identity.cdx.json
└── v907-verify.cdx.json
```

`envelope.json` is the at-a-glance aggregate. `metrics.prom` is
the Prometheus-textfile snapshot. The 15 `*.cdx.json` files are
the CycloneDX-1.5 SBOMs.

## 3. Re-generating locally (stdlib mode, hermetic)

The generator is stdlib-only (`tomllib` + `argparse` + `json`).
No `cargo`, no network, no plugin install required.

```bash
mkdir -p out/sbom
python3 scripts/observability/generate-15-binary-sbom.py \
    --cargo-lock wirelang-rust/Cargo.lock \
    --out-dir out/sbom \
    --out-envelope out/sbom/envelope.json \
    --out-textfile out/sbom/metrics.prom \
    --out-markdown out/sbom/summary.md \
    --format cyclonedx-1.5 \
    --mode stdlib
```

Switches:

- `--format` — `cyclonedx-1.5` (default) or `spdx-2.3`.
- `--generator-ts` — override the timestamp for reproducible
  output (use for byte-stable comparison against a baseline).
- `--mode stdlib` — pure-Python walker (the daily CI default).
- `--mode cargo-cyclonedx` — fall-back to upstream plugin
  (operator-hand only — needs `cargo-cyclonedx` on PATH).

Verify the output:

```bash
ls -1 out/sbom/*.cdx.json | wc -l   # must print 15
python3 -m json.tool out/sbom/envelope.json | head -20
```

## 4. Operator-Hand: `cargo-cyclonedx` fall-back

For a deeper SBOM that uses Cargo's own dependency resolver
(handles target-conditional and feature-gated deps with full
fidelity), an operator with `cargo-cyclonedx` installed on
PATH can run:

```bash
# Pre-req: cargo install cargo-cyclonedx
mkdir -p out/sbom-cargo
python3 scripts/observability/generate-15-binary-sbom.py \
    --cargo-lock wirelang-rust/Cargo.lock \
    --workspace-root wirelang-rust \
    --out-dir out/sbom-cargo \
    --format cyclonedx-1.5 \
    --mode cargo-cyclonedx
```

If `cargo-cyclonedx` is not on PATH, the script falls back to
stdlib-mode silently and prints a warning to stderr.

**Do NOT run `--mode cargo-cyclonedx` in CI.** It is not
hermetic against the Cargo registry, and the daily workflow
intentionally pins to stdlib-mode for determinism.

## 5. Cross-check against cosign-policy inventory

The generator's `TAG45_BINARY_INVENTORY` constant must stay
byte-identical to the policy YAML's `binaries[].name` list. The
hermetic test `test_TV_AN_01_inventory_matches_cosign_policy`
enforces this on every PR.

Manual check:

```bash
python3 -c '
import importlib.util, sys
spec = importlib.util.spec_from_file_location(
    "gen",
    "scripts/observability/generate-15-binary-sbom.py",
)
gen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gen)
print(gen.TAG45_BINARY_INVENTORY)
'

grep '^  - name:' policies/cosign-policy-phase-3b.yaml \
    | sed 's/^  - name: //'
```

The two lists must match byte-for-byte. If they drift, the
generator update goes in the same PR as the policy update
(Tag-45 cross-substrate parity contract).

## 6. Substrate growth path

If a future Welle adds an N-th binary (e.g. a Welle-8 closeout
adds a 16th cosign-policy entry):

1. Update `policies/cosign-policy-phase-3b.yaml` (add binary).
2. Update `TAG45_BINARY_INVENTORY` in the generator.
3. Update `POLICY_NAME_TO_CRATE` in the generator with the new
   binary -> source crate mapping.
4. The hermetic test `test_TV_BU_01_bundle_has_fifteen_binaries`
   must be updated to the new count (search-and-replace `15`).
5. The workflow's post-generate sanity check (`count -ne 15`)
   must be updated in the same PR.

All five updates land in a single PR for cross-substrate
parity.

## 7. Anchors

- Tag-45 PR #294 — Quadlet+Cosign 15-Binary substrate refresh.
- Tag-46 PR #298 — A6 substrate-layer coverage matrix.
- Tag-47 PR #307 — Cosign-Keyless-OIDC-Drift-Probe (time-axis).
- ADR-0066 §AR-Hand-Gate — pre-cutover sign-off pre-condition.
- CycloneDX spec v1.5 (industry-standard).
- SPDX spec v2.3 (industry-standard).
- feedback_sandbox_host_trennung.md — no live cargo I/O from
  sandbox.

— Kai
