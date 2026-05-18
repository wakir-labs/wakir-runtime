# `state/sbom-baseline-refresh-receipts/` — Refresh Audit Trail (Tag-50)

Append-only directory of refresh-receipt JSON envelopes emitted
by the Tag-50 CLI
(`scripts/observability/refresh-15-binary-sbom-baseline.py`) and
the dispatch-only workflow
(`.github/workflows/sbom-baseline-refresh.yml`).

Each receipt records:

- `approval_token` — the AR-Hand-Gate token typed by the operator
  (format `AR-HAND-GATE-YYYY-MM-DD-<initials>`).
- `cargo_lock_sha256_before` / `cargo_lock_sha256_after` — the
  cargo-lock state pinned by the baseline before vs. after the
  refresh.
- `pre_refresh_verdict` + `pre_refresh_drift_total` +
  `pre_refresh_checksum_changed_count` — the drift summary that
  AR signed off on.
- `post_refresh_verdict` — must be `GREEN` for the refresh to
  count as successful.
- `files_written` — the fifteen baseline files that were
  overwritten.
- `operator_invocation` — the CLI/workflow argument snapshot.

## Audit-trail property

Every refresh emits exactly one receipt. The receipt is the
single source of truth for "which AR sign-off blessed this
baseline mutation". Internal Audit (Henrik) reads this
directory to reconstruct the dependency-tree provenance trail.

## Do NOT delete

Receipts are append-only. Removing a receipt breaks the audit
chain; if a receipt is found to be wrong, append a correction
receipt (with a `correction_of` field pointing to the prior
receipt's filename) rather than deleting.

## Anchors

- Tag-50 — refresh CLI + workflow + this directory.
- Tag-49 PR #318 — daily verifier + baseline directory.
- Tag-48 PR #310 — 15-binary SBOM generator.
- ADR-0066 § AR-Hand-Gate.
- `docs/operations/15-binary-sbom-baseline-refresh.md` — operator runbook.

— Kai
