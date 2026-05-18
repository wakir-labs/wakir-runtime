# `state/sbom-baseline/` — 15-Binary SBOM Baseline (Tag-49)

Pinned, AR-approved SBOM snapshot per Tag-45 binary. The
Tag-49 daily verification workflow
(`.github/workflows/sbom-verification-daily.yml`) compares the
freshly-generated SBOMs (Tag-48 generator) against these files
and emits a Mira-Notify event on drift.

## Files

Fifteen files matching the Tag-45 inventory:

```
anchor-emitter.json
bridge-audit-replay.json
bridge-audit-writer.json
bridge-diff.json
fsm.json
fsm-welle5.json
migrate-version.json
recovery.json
recovery-welle7.json
state-backing.json
state-backing-welle4.json
subscribe-loop.json
subscribe-loop-welle6.json
svid-workload-identity.json
v907-verify.json
```

Each file is a CycloneDX-1.5 JSON document — byte-identical to
what the Tag-48 generator produces against the pinned
`wirelang-rust/Cargo.lock` (with `--generator-ts 0.0` for
deterministic embedded metadata).

## Refresh procedure

See `docs/operations/15-binary-sbom-baseline-refresh.md`. The
refresh is Operator-Hand only, gated by AR sign-off.

Tag-50 introduced the automated CLI
(`scripts/observability/refresh-15-binary-sbom-baseline.py`) and
the `workflow_dispatch`-only workflow
(`.github/workflows/sbom-baseline-refresh.yml`). Receipts land
in `state/sbom-baseline-refresh-receipts/` for the audit trail.

## Do NOT edit by hand

These files are emitted by the generator. Hand-editing breaks the
substrate-consistency check on the embedded
`wakir:cargo-lock-sha256` property.

## Anchors

- Tag-48 PR #310 — generator that produced these baselines.
- Tag-49 — verifier + workflow that consume these baselines.
- ADR-0066 §AR-Hand-Gate — pre-cutover sign-off bundle.
