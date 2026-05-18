<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

# 15-Binary Build-Reproducibility Audit — Operator Recipe (Tag-51, Kai)

This runbook accompanies
`scripts/observability/verify-15-binary-build-reproducibility.py`
(Tag-51, Kai) and the daily workflow at
`.github/workflows/build-reproducibility-daily.yml`.

It tells an operator how to:

1. Read the build-reproducibility verdict in the GitHub-Actions
   run summary.
2. Re-run the audit locally (stdlib-mode, hermetic).
3. Triage a RED verdict (one or more binaries non-deterministic).
4. Spot-check the per-binary fingerprint against an earlier audit.

## 1. Context

The Phase-3a-Foundation 15-binary substrate is now pinned across
six provenance surfaces:

- `policies/cosign-policy-phase-3b.yaml` — Tag-45 cosign-policy
  inventory.
- `wirelang/specs/wirelang-spec-v0-4.md` §3.1 — Tag-45 spec
  reference catalogue.
- Tag-47 PR #307 — Cosign-Keyless-OIDC-Drift-Probe.
- Tag-48 PR #310 — 15-binary SBOM generator.
- Tag-49 PR #318 — SBOM-vs-baseline verifier.
- Tag-50 PR #323 — SBOM-baseline-refresh CLI.

**Tag-51 (this deliverable)** adds a seventh axis: *fingerprint-
derivation determinism*. The earlier axes assume the build-graph
derivation is byte-stable across invocations. If that assumption
silently breaks (a dict-ordering bug, a timestamp leak, an env-var
leak into the hash), the SBOM-baseline verifier would still report
GREEN but two operators on the same source tree would produce
distinct attestation chains. Tag-51 catches that failure-mode
explicitly: it runs the derivation twice in a single invocation
and asserts byte-equal SHA-256 fingerprints per binary.

When AR signs off a Welle (per ADR-0066 §AR-Hand-Gate), the
audit-trail bundle now includes:

- Cosign-verified image digest.
- OIDC-drift-probe verdict (Tag-47).
- 15-binary SBOM bundle (Tag-48).
- SBOM-vs-baseline verdict (Tag-49).
- **Build-reproducibility verdict (Tag-51, this gauge).**

## 2. Reading the daily Job-Summary

The workflow runs at 07:45 UTC daily. Open the latest run from the
Actions tab → `build-reproducibility-daily` and scroll to the
Job-Summary. You will see:

```text
## 15-Binary Build-Reproducibility Audit

**Overall**: `GREEN`
**Cargo.lock SHA-256**: `bc7f1651...`
**Deterministic**: 15 / 15
**Drift**: 0

| Binary | Deterministic | Pass-1 SHA (prefix) | Pass-2 SHA (prefix) |
| ... 15 rows ... |
```

A `GREEN` overall verdict with `15 / 15` deterministic and 12-char
matching SHA prefixes per row is the expected daily state.

A `RED` overall verdict means one or more binaries produced
distinct fingerprints across the two passes — supply-chain
provenance is compromised until the root cause is identified.
See §4 below.

## 3. Re-running the audit locally (hermetic, stdlib-only)

```bash
mkdir -p out/build-reproducibility
python3 scripts/observability/verify-15-binary-build-reproducibility.py \
    --cargo-lock wirelang-rust/Cargo.lock \
    --out-json out/build-reproducibility/verdict.json \
    --out-textfile out/build-reproducibility/metrics.prom \
    --out-markdown out/build-reproducibility/summary.md \
    --out-mira-notify out/build-reproducibility/mira-notify.json
```

Exit codes:

- `0` — GREEN, all 15 binaries deterministic.
- `1` — input / argument error.
- `2` — RED, one or more binaries non-deterministic.

The verifier emits an empty `mira-notify.json` on GREEN (zero bytes,
treated as a probe-ran marker). On RED it emits a structured event
with `severity: "RED"`, `event_type: "build-reproducibility-drift"`,
and the list of drift binaries.

## 4. Triaging a RED verdict

A RED verdict from a stdlib-hermetic derivation is a substrate-
side regression in the verifier itself, NOT a real-world Cargo
non-determinism (the two passes both parse the same Cargo.lock
in the same process). The expected RED causes are:

1. **Dict-ordering leak.** A future refactor of the fingerprint
   derivation introduces a dict iteration that is not pre-sorted.
   Fix: sort the source iterable before hashing.
2. **Timestamp leak.** A future refactor binds `audit_ts` into
   the hash. Fix: keep the timestamp in the envelope, never in
   the fingerprint.
3. **Env-var leak.** A future refactor reads an env-var inside
   the fingerprint path. Fix: pass all inputs as function args.
4. **Floating-point round-trip.** A future schema change adds a
   float field that serializes non-deterministically. Fix: cast
   to canonical-string form before hashing.

Triage procedure on RED:

1. Identify the drift binaries from the Mira-Notify event.
2. Reproduce locally with `--out-json drift.json` and inspect
   `per_binary[*]` for the diverging entries.
3. Add a print-statement at the top of `fingerprint_binary` to
   dump every line that is fed into the hasher.
4. Compare the per-line dump across two invocations to identify
   the non-deterministic line.
5. Fix the source of non-determinism, then re-run the audit to
   confirm GREEN.
6. Open a regression-test PR that codifies the failure-mode as a
   hermetic invariant in
   `tests/observability/test_verify_15_binary_build_reproducibility.py`.

## 5. Spot-checking against an earlier audit

The verifier writes the canonical fingerprint to
`out/build-reproducibility/verdict.json`. To compare today's
fingerprints against an earlier audit:

```bash
jq '.per_binary[] | {binary_name, pass1_fingerprint_sha256}' \
    old-verdict.json > /tmp/old.txt
jq '.per_binary[] | {binary_name, pass1_fingerprint_sha256}' \
    out/build-reproducibility/verdict.json > /tmp/new.txt
diff /tmp/old.txt /tmp/new.txt
```

A fingerprint change between two audits is normal and expected
whenever Cargo.lock changes (any new dep, version bump, or
checksum rotation will rotate the fingerprint). A fingerprint
change *without* a corresponding Cargo.lock SHA-256 change is
the substrate-regression failure-mode this audit defends against.

## 6. Cross-references

- ADR-0066 §AR-Hand-Gate — provenance bundle requirement.
- `docs/operations/15-binary-sbom-generator.md` — Tag-48
  generator runbook.
- `docs/operations/15-binary-sbom-baseline-refresh.md` — Tag-49
  refresh runbook.
- `feedback_sandbox_host_trennung.md` — sandbox-boundary rule.

— Kai
