<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

# Cross-repo mirror-pair sync status

Status log of point-in-time sync verifications between mirror-pair
files in `wakir-runtime` (BUSL-dominant) and `wakir-protocol`
(Apache-2.0 + CC-BY-4.0).

This file complements `.cross-repo-drift-allowlist.yaml` and the
`cross-repo-drift-audit` GitHub Actions workflow:

* The **allowlist** waives structurally-tolerated byte drift on
  audited mirror-pairs (currently the 10 Layer-0/1/2 JSON schemas,
  the canonical caveat set, and Identity-Substrate primitives —
  see `.github/workflows/cross-repo-drift-audit.yml`).
* This **status log** records ad-hoc sync verifications on *non*-
  audited mirror-pairs (notably the prose spec documents under
  `wirelang/specs/` <-> `wakir-protocol:docs/`, per the Cut-2
  protocol-substance classification in
  `docs/decisions/cut2-protocol-substance-classification.md`
  §I).

The two artefacts have intentionally different roles:

* The allowlist is CI-checked and forms a contract.
* This status log is a low-friction trail of one-shot manual
  verifications. It is not enforced by CI. A clean status entry
  here does **not** imply future bytes will remain identical —
  follow-up sync verifications must re-run.

## Wirelang Spec v0.2.1 — §13 Subscribe-Mode (Reza PR #77)

| Field | Value |
| --- | --- |
| Sprint | Sprint-Wirelang-Spec-Sync-Cross-Repo-MINI |
| Date | 2026-05-16 |
| Runtime path | `wirelang/specs/wirelang-spec-v0-2.md` |
| Protocol path | `docs/wirelang-spec-v0-2.md` |
| Runtime baseline SHA | `e1a3dab0e5c7dd65292597948c55306324c99891` |
| Protocol baseline SHA | `575898c7692a66f6c9b3c6fdb8d44108870d8abf` |
| File-content SHA-256 | `d63f216efbe4f98b3422b4fea4aa1f1db737e3bb483bc5a70d06639cac4e4880` |
| Drift | **clean (byte-identical)** |
| In `cross-repo-drift-audit` mirror-pair table? | no — prose spec, file-level CC-BY-4.0 per `cut2-protocol-substance-classification.md` §I |
| Allowlist action | none — pair is not in the audit surface |

### Verification command (for re-runs)

```bash
# from a fresh clone of each repo at the recorded baseline SHA
sha256sum \
  wakir-runtime/wirelang/specs/wirelang-spec-v0-2.md \
  wakir-protocol/docs/wirelang-spec-v0-2.md
# expect both lines to start with d63f216e...
```

### Cross-references

* Reza PR #77 — Wirelang-Spec v0.2.1 §13 Subscribe-Mode introduction
  (both repos updated in lock-step in the same sprint).
* Reza PR #105 — cross-repo-drift-audit workflow (audit-only mode).
* Reza PR #111 — hermetic tests for the drift-audit workflow logic.
* Reza PR #126 — Enforce-flip readiness (1-way migration strategies
  §3).
* ADR-0062 Cut-2 — protocol substance classification.

## Followups

* If `wirelang-spec-v0-2.md` is ever lifted into the audited mirror
  surface (e.g. by extending the `pairs=( ... )` array in
  `cross-repo-drift-audit.yml`), this log row is the seed for the
  baseline allowlist entry. Today it is **not** in scope.
* Future spec-doc sync verifications append a new row above.
