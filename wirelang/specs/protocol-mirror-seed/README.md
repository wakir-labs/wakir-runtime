<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors -->

# Protocol-Mirror-Seed (Tag-59 Cut-3)

**Owner:** Reza Tehrani (Wirelang / Spec)
**Date introduced:** 2026-05-19 (Tag-59 marathon)
**Anchor:** Tag-58 Noa Audit (PR #373) Mirror-Drift baseline (4 x
`missing-protocol` verdicts).

---

## 1. Purpose

This tree is the **protocol-side seed** for the Tag-58 Alert-Routing
cross-repo mirror audit
(`tooling/ci/audit_alert_routing_cross_repo_mirror.py`). Sandbox-
boundary discipline (ADR-0023a) forbids Reza from writing to the
`wakir-protocol` repo directly. Instead, the Tag-59 Cut-3 lands the
canonical protocol-side spec files inside `wakir-runtime` under a
strictly-scoped seed path:

```
wirelang/specs/protocol-mirror-seed/
   docs/observability/pre-mortem-failure-mode-notify-catalog.md
   dashboards/phase-3-marathon-alerts.yaml
   dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml
   scripts/observability/alert-rule-to-mira-notify-bridge.py
```

Once Tomás Cross-Review-Zone-I has signed off, an Engineering-Lead
hand-off PR will mirror these files into the `wakir-protocol` repo
at their canonical paths. After that mirror PR lands, the seed
files in `wakir-runtime` may either be removed or kept as a
sandbox-side reference snapshot (the audit is independent of
whether the seed survives).

## 2. License / SPDX policy

All four files in this tree carry **`SPDX-License-Identifier:
Apache-2.0`** to match the protocol-side licensing posture (vs. the
runtime-side BUSL-1.1 on the originals). The canonicaliser in the
mirror audit strips SPDX/copyright headers before SHA-256, so
license-banner asymmetry does **not** trigger drift verdicts.

## 3. Boundary

This tree is read-only for Tomás / WAT / SRE rotation in Phase-3.
Only Reza (Wirelang) edits the seed; the protocol-side mirror PR is
the only path to land the canonical content in `wakir-protocol`.

## 4. Audit hook

The Tag-58 audit script learns a new stage in Tag-59:
`protocol-mirror-seed-detect`. When the seed file exists in the
runtime tree at `wirelang/specs/protocol-mirror-seed/<path>`, the
audit emits a **Cut-3 sync-marker** verdict line (not a drift). The
marker is informational: it signals that a Cut-3 hand-off PR for
the corresponding mirror-pair is **ready to be opened against
`wakir-protocol`** by the Engineering-Lead.

The marker does **not** flip the existing `missing-protocol`
verdict — that flip only happens when the protocol-side file
actually lands at its canonical path. The marker is a separate
signal, surfaced alongside the verdict.

## 5. Reference

* Tag-58 audit: `tooling/ci/audit_alert_routing_cross_repo_mirror.py`
* Tag-58 PR #373 (Noa SRE) — Mirror-Audit introduction
* Tag-59 PR (this PR) — Cut-3 Protocol-Side Seed
* ADR-0023a — Sandbox-Boundary discipline (Reza must not write
  `wakir-protocol` directly)

-- Reza
