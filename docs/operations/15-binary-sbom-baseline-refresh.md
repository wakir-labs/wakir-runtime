# 15-Binary SBOM Baseline Refresh — Operator Runbook (Tag-49)

**Owner:** Kai Hoffmann (Dev-Engineering-3)
**Audience:** Operator-Hand + AR-Hand-Gate sign-off
**Cadence:** On dependency-tree change accepted by AR; on Welle
sign-off; ad-hoc on supply-chain advisory.

## What this runbook covers

The Tag-49 SBOM-Verification-Workflow
(`.github/workflows/sbom-verification-daily.yml`) compares the
daily-generated 15-binary SBOMs against the pinned baseline in
`state/sbom-baseline/`. When the verdict is non-GREEN, a
Mira-Notify event is emitted with `severity=page` (RED) or
`severity=warning` (YELLOW).

This runbook is what the operator runs when AR has approved the
new dependency-tree state and the baseline must be refreshed.

## Tag-50 — automated path

The Tag-50 refresh CLI
(`scripts/observability/refresh-15-binary-sbom-baseline.py`)
collapses the seven-step manual sequence below into a single
invocation guarded by an `--approval-token` argument:

```bash
# Dry-run preview (no state mutation, no token required):
python3 scripts/observability/refresh-15-binary-sbom-baseline.py \
    --dry-run \
    --receipt-out /tmp/refresh-preview.json

# Live refresh (token required, format checked client-side):
python3 scripts/observability/refresh-15-binary-sbom-baseline.py \
    --approval-token AR-HAND-GATE-2026-05-19-fred \
    --receipt-out state/sbom-baseline-refresh-receipts/$(date -u +%Y%m%dT%H%M%SZ)-receipt.json
```

The CLI:

1. Runs the Tag-48 generator with `--generator-ts 0.0` (deterministic).
2. Runs the Tag-49 verifier in pre-refresh mode → captures drift.
3. Blocks if `checksum-changed` drift is present unless
   `--allow-checksum-changed` is also supplied.
4. Copies the generated SBOMs into `state/sbom-baseline/`.
5. Re-runs the verifier — asserts `GREEN`.
6. Emits a refresh-receipt JSON capturing the AR token + drift
   summary + cargo-lock-sha256 before/after.

The CI surface is `.github/workflows/sbom-baseline-refresh.yml`
(workflow_dispatch only — NEVER scheduled). The workflow runs
the same CLI; the operator clicks "Run workflow" in the Actions
tab and supplies the token + dry-run flag.

The seven-step manual sequence below remains valid as the
fallback procedure (e.g. when the CLI itself needs debugging)
and as the authoritative narrative of the refresh semantics.

## When NOT to run this

- The daily verifier is YELLOW/RED, but no AR sign-off for the
  drift exists. **Do not refresh.** First triage the drift,
  understand which crate changed and why, then bring to AR.
- The drift is a `checksum-changed` event on a `crates.io`
  package. **Stop.** That is a supply-chain integrity signal —
  the same `(name, version)` pair must NEVER produce a different
  SHA-256 tarball hash. Escalate to Internal Audit (Henrik) and
  CTO (Priya) before any refresh.

## When TO run this

- AR approved a new Welle that adds/removes/updates Rust deps.
- A planned `cargo update` was merged and AR signed off.
- A new binary was added to the Tag-45 inventory (in which case
  the inventory in `scripts/observability/generate-15-binary-sbom.py`
  must be updated first — separate PR).

## Steps

### 1. Confirm the cargo-lock SHA-256

```bash
sha256sum wirelang-rust/Cargo.lock
```

Record the value. The new baseline will embed it.

### 2. Run the generator to produce a fresh bundle

The same generator the Tag-48 daily workflow runs. Use
`--generator-ts 0.0` for deterministic embedded metadata so the
baseline files compare byte-for-byte across machines:

```bash
mkdir -p /tmp/sbom-baseline-refresh
python3 scripts/observability/generate-15-binary-sbom.py \
    --cargo-lock wirelang-rust/Cargo.lock \
    --out-dir /tmp/sbom-baseline-refresh \
    --out-envelope /tmp/sbom-baseline-refresh/envelope.json \
    --format cyclonedx-1.5 \
    --generator-ts 0.0
```

The output contains fifteen `<binary>.cdx.json` files plus
`envelope.json`.

### 3. Diff against the current baseline

```bash
python3 scripts/observability/verify-15-binary-sbom-against-baseline.py \
    --sbom-dir /tmp/sbom-baseline-refresh \
    --baseline-dir state/sbom-baseline \
    --out-json /tmp/sbom-baseline-refresh/verify.json \
    --out-markdown /tmp/sbom-baseline-refresh/verify.md \
    --generator-ts 0.0
```

Read `/tmp/sbom-baseline-refresh/verify.md`. The drift list is the
exact diff the operator hands AR for sign-off.

### 4. Capture the AR sign-off

In the PR description (or AR-Hand-Gate doc) capture:

- The cargo-lock SHA-256 before and after.
- The list of components added / removed / version-changed.
- Any `checksum-changed` entries — these MUST be justified
  (yanked-then-republished crate? confirmed via crates.io
  metadata + Internal Audit review).
- AR sign-off line: `AR-Hand-Gate: approved <date> <name>`.

### 5. Refresh the baseline files

```bash
for f in /tmp/sbom-baseline-refresh/*.cdx.json; do
  base=$(basename "$f" .cdx.json)
  cp "$f" "state/sbom-baseline/${base}.json"
done
```

### 6. Verify the refresh produces GREEN

```bash
python3 scripts/observability/verify-15-binary-sbom-against-baseline.py \
    --sbom-dir /tmp/sbom-baseline-refresh \
    --baseline-dir state/sbom-baseline \
    --generator-ts 0.0
```

Expected output:

```
[verdict=GREEN] ok=15 yellow=0 red=0 missing=0 cargo-lock-sha256=...
```

### 7. Commit + PR

```bash
git add state/sbom-baseline/
git commit -m "ops(sbom-baseline): refresh Tag-NN baseline after AR sign-off"
```

PR description must reference the AR-Hand-Gate sign-off, the
cargo-lock SHA-256 before/after, and the drift summary.

## Failure-mode catalog

| Symptom | Drift class | Operator action |
|---|---|---|
| `component-added` only | YELLOW | Standard AR-sign-off; refresh expected. |
| `component-removed` only | YELLOW | Confirm intentional; refresh after AR. |
| `version-changed` only | YELLOW | Confirm `cargo update` was intentional; refresh after AR. |
| `checksum-changed` | RED | STOP. Supply-chain event. Escalate to Henrik + Priya. |
| `MISSING-BASELINE` | RED | A baseline file is missing. Restore from previous commit; do NOT refresh forward to hide the deletion. |
| Per-binary `current_cargo_lock_sha256` differs from aggregate | RED | Substrate inconsistency. Re-run generator; if persists, file Internal Audit ticket. |

## Mira-Notify event surface

When the daily workflow detects non-GREEN, it emits one event with:

- `alert_name=SBOMVerificationDrift`
- `severity=page` (RED) or `severity=warning` (YELLOW)
- `runbook_url` -> this document
- `labels.verdict={GREEN,YELLOW,RED}`
- `source=sbom-verification-daily-workflow`

The Mira-Notify receiver materialises an inbox file in
`agents-workspaces/mira/inbox/`. Operator-Hand reads the inbox
file + Job-Summary + envelope artefact to triage.

## Anchors

- ADR-0066 §AR-Hand-Gate — pre-cutover sign-off bundle.
- Tag-48 PR #310 — 15-binary SBOM generator.
- Tag-49 — this verifier + workflow + baseline state.
- `feedback_sandbox_host_trennung.md` — no live cargo I/O.
- `docs/observability/pre-mortem-failure-mode-notify-catalog.md` —
  Mira-Notify event-schema reference.

— Kai
