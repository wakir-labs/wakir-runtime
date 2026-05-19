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

<!-- REUSE-IgnoreStart -->
All four files in this tree carry **`SPDX-License-Identifier:
Apache-2.0`** to match the protocol-side licensing posture (vs. the
runtime-side BUSL-1.1 on the originals). The canonicaliser in the
mirror audit strips SPDX/copyright headers before SHA-256, so
license-banner asymmetry does **not** trigger drift verdicts.
<!-- REUSE-IgnoreEnd -->

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

---

## 6. Tag-61 extension — schemas/ sub-tree (Reza)

Tag-61 (2026-05-19) re-uses this seed pattern for a *second* cross-
repo audit: `tooling/ci/audit_cross_repo_drift_allowlist.py` (Noa
Tag-60). The Tag-31 BASELINE_INVENTORY locks `clean=4, drift=6` —
the four drift rows with re-sync strategies are:

| runtime path                                       | protocol path                                                | strategy                       |
|---                                                 |---                                                           |---                             |
| `wirelang/schemas/layer-0-transport.json`          | `wakir_protocol/schemas/layer-0-transport.json`              | re-sync-protocol-from-runtime  |
| `wirelang/schemas/layer-1-wire.json`               | `wakir_protocol/schemas/layer-1-wire.json`                   | re-sync-protocol-from-runtime  |
| `wirelang/schemas/layer-2-semantic.json`           | `wakir_protocol/schemas/layer-2-semantic.json`               | re-sync-protocol-from-runtime  |
| `wirelang/schemas/aip-document.json`               | `wakir_protocol/schemas/aip-document.json`                   | re-sync-runtime-from-protocol  |

Each row gets a canonical-form mirror at
`wirelang/specs/protocol-mirror-seed/schemas/<basename>.json`. The
seed files are byte-identical structural mirrors of the runtime
schemas (license posture: Apache-2.0, same as the rest of the seed
tree). They serve as **post-re-sync trajectory** signal to the
Tag-60 audit helper:

* Stage 3 keeps the locked `coverage=1.0, trajectory=0.40,
  score=76 / ENFORCE-CAUTION` baseline of record.
* Stage 3b counts seed-presence and computes
  `post_resync_trajectory = (clean + seeded) / total` and a
  `post_resync_score`. With all 4 seeds present:
  `post_trajectory = (4 + 4) / 10 = 0.80`, `post_score = 60 +
  32 = 92 → ENFORCE-READY`.

The post-resync verdict does **not** flip the locked verdict; both
are surfaced side-by-side. The Engineering-Lead hand-off PR that
mirrors these seed files into `wakir-protocol` at their canonical
paths is the only path that turns the locked baseline trajectory.

The `--post-resync` CLI flag promotes the audit to gate on the
post-resync verdict — useful once the hand-off PR is queued.

-- Reza
