<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# docs/archive — historical evidence, not product surface

This directory holds artefacts that are kept for evidentiary value only.
Nothing here is part of the runtime, the proof path, or the operator
documentation. Do not link to it from code or from active docs except
as historical reference.

## Full pre-cleanup tree

The complete repository state before the Phase-4 public-surface
cleanup (ADR-0072, sub-item 4d) is addressable via the annotated tag
`archive/pre-phase-4` (commit `58794eb`, 2026-05-20). Everything that
was deleted in the cleanup — the Phase-3 cutover workflows, their CI
helpers, tests, runbooks, state files and fixtures — can be recovered
from that tag:

```bash
git fetch origin --tags
git show archive/pre-phase-4:.github/workflows/phase-3-marathon-rollback.yml
git checkout archive/pre-phase-4 -- docs/phase-3c/   # restore a directory
```

## Contents

| Path | What it is | Why it is kept |
|---|---|---|
| `evidence/phase-3/phase-3-complete-marker.json` | Phase-3-COMPLETE marker emitted 2026-05-20 (AC-1..AC-5 conjunction) | OTS-attested milestone evidence |
| `evidence/phase-3/phase-3-complete-marker.json.ots` | OpenTimestamps proof for the marker | independent verifiability of the milestone |
| `evidence/phase-3/henrik-phase-3-complete-ratification.json` | Internal-audit ratification stamp for the marker | audit trail of the milestone |
| `evidence/phase-3/ar-hand-phase-3-complete-stamp.json` | Supervisory-board ratification stamp for the marker | audit trail of the milestone |
| `reports/live-vm/` | Live-VM pre-cutover probe reports, 2026-05-18 (7 files) | evidence for the live-bring-up gap between hermetic CI and real VMs |
| `evidence/wat-live-runs/` | WAT TV-1 / TV-2 / TV-3 live-run and live-stamp memos, 2026-05-06/07 (6 files) | first real Bitcoin-anchored runs of the WAT pipeline (calendar receipts, block heights, Esplora confirmations) |
| `evidence/audits/2026-05-18-nats-jetstream-subjects-audit.md` | First generated run of the NATS-JetStream subjects / publish-mode audit (0 drift rows) | baseline referenced by `wirelang/specs/wirelang-spec-v0-4.md` §8; the audit itself still runs via `scripts/audit/nats-jetstream-subjects-audit.py` |
| `evidence/audits/phase-3a-15-crate-consistency-2026-05-19.md` | Phase-3a 15-crate consistency audit (Python ↔ Rust ↔ pin-pack) | reconciliation basis for spec v0.4.1 / v0.4.2; pinned by `tests/audit/test_phase_3a_15_crate_consistency.py` |
| `evidence/audits/persona-engine-0-5-3-production-readiness-2026-05-19.md` | Persona-Engine 0.5.3 production-readiness audit (D1–D7 verdicts) | release evidence for the shipped 0.5.3 engine; pinned by `wirelang/tests/persona_engine/test_production_readiness_audit_0_5_3.py` and the engine-version-drift allowlist |
| `evidence/audits/persona-engine-0-5-2-production-readiness-2026-05-19.md` | Persona-Engine 0.5.2-final-pre-cutover production-readiness audit (seven dimensions) | predecessor release evidence for the 0.5.3 audit; pinned by `wirelang/tests/persona_engine/test_production_readiness_audit_0_5_2.py` |
| `evidence/audits/adr-spec-compliance-audit-2026-05-19.md` | ADR ↔ spec compliance audit (drift summary per ADR) | basis of the six path errata below; pinned by `wirelang/tests/test_adr_spec_compliance_audit.py` |
| `evidence/decisions/adr-errata-path-typo-fixes.md` | Errata addendum ERR-S1..S6 for path typos in accepted ADRs | records corrections to accepted decision records; pinned by `wirelang/tests/test_adr_errata.py` |
| `evidence/decisions/spiffe-jwt-svid-identity-sketch.md` | Phase-2 design sketch for the SPIFFE/SPIRE JWT-SVID container identity (trust-domain format, SPIFFE-ID shape, NATS JWT refresh pattern) | superseded by the shipped identity substrate; still the only written record of why the ID components look the way they do, cross-referenced from `docs/nats-jwt-auth-phase-2-4.md` |
| `evidence/decisions/capability-token-layer-snapshot.md` | Point-in-time snapshot of the AIP + Biscuit capability-token layer (module inventory, gap list) | superseded implementation-status record, kept until the capability-token spec carries the same inventory |
| `evidence/decisions/doppelbetrieb-bridge-smoke-acceptance.md` | Acceptance rationale for the dual-operation federation bridge smoke gate | records why the two-emitter smoke shape was accepted |
| `evidence/decisions/anthropic-prompt-caching-phase-2a.md` | Delivery record for the prompt-caching payload builder and telemetry (phase 2a) | closed delivery note, superseded by the shipped module and its tests |
| `evidence/decisions/phase-3-nodeattestor-migration.md` | Tracking note for the planned `x509pop` NodeAttestor migration | historic planning note; phase 3 is complete, the migration was not executed |
| `dead-dashboards/` (5 files) | Grafana dashboards and alert definitions whose panels query metrics no longer produced by any script: the cutover-morning verdict tile, the cross-wave coordination board, the wave-status board, the per-wave trend heatmap and the migration-marathon SLO board | staged for deletion, not evidence — the migration they observed is complete and their producers are gone. Recoverable from tag `archive/pre-phase-4` |
| `dead-migration-tooling/cutover-day-watch.sh` | Bash wrapper that ran the migration-day live-stream aggregator in a watch loop and forwarded drift crossings to the notify queue | staged for deletion — the cutover day it drove is past and nothing references the script |
| `dead-migration-tooling/cutover-day-watch-runbook.md` | Operator runbook for the migration-day watch loop | staged for deletion — describes a one-off event that ended 2026-05-20 |
| `dead-migration-tooling/pre-cutover-watch-day-spec.md` | Specification of the pre-cutover watch day (dashboard inventory D1-D7, trigger catalogue, verdict rules) | staged for deletion — the watch day it specifies is past; the verdict script it inspired still ships |
| `dead-migration-tooling/pre-cutover-probe-dashboard.md` | Dashboard spec for the pre-cutover probe failure-rate view | staged for deletion — probe window closed |
| `dead-migration-tooling/per-welle-trend-heatmap-runbook.md` | Runbook for the per-wave trend heatmap | staged for deletion — the heatmap dashboard is gone with it |
| `dead-migration-tooling/sli-slo-phase-3-marathon.md` | SLI/SLO catalogue for the migration marathon | staged for deletion — superseded by `docs/observability/sli-slo-phase-1b.md` and `sli-slo-wat-phase-2.md`, which cover the surviving services |
| `dead-migration-tooling/watch-day-operator-trigger-audit-trail-marker-catalog.md` | Catalogue of audit-trail markers the watch-day operator was to emit | staged for deletion — no consumer left |

| `dead-tests/test_trajectory_resync_cross_repo_drift_score.py` | Audit suite for the cross-repo drift re-sync *score* ("92 / ENFORCE-READY") produced by the `tooling/ci/audit_cross_repo_drift_allowlist.py` helper removed in PR #526 | staged for deletion — the helper is gone and the score pinned a migration state that no longer exists; its surviving invariants (mirror-seed presence, JSON validity, SPDX posture, byte-equality with `wirelang/schemas/`) are carried forward in `tests/audit/test_protocol_mirror_seed_integrity.py` |
| `dead-migration-tooling/per-wave-trend-heatmap.py`, `per-wave-heatmap-prom-emitter.py` | Generator and Prometheus emitter for the per-wave trend heatmap | staged for deletion — the dashboard and its runbook are already archived here, so the pair produced metrics nothing rendered |
| `dead-migration-tooling/cutover-day-live-stream-aggregator.py` | Aggregator behind the migration-day live-stream dashboard | staged for deletion — the watch loop that drove it is archived and the cutover day ended 2026-05-20 |
| `dead-migration-tooling/watch-day-practice-run.py`, `pre-cutover-watch-day-verdict.py` | Practice-run driver and verdict rules for the pre-cutover watch day | staged for deletion — the watch-day spec and runbook are already archived here |
| `dead-migration-tooling/verify_marathon_closeout.py` | Closeout aggregator that bundled the seven per-wave verifier verdicts into one MARATHON-CLOSEOUT verdict | staged for deletion — the migration it closed out completed on 2026-05-20 |
| `dead-dashboards/phase-3c-cutover-day-live-stream.json` | Live-stream dashboard for the migration cutover day | staged for deletion — its aggregator is archived with it |
| `dead-tests/` (6 files) | The QA suites that pinned the archived migration tooling above: per-wave heatmap, live-stream aggregator, watch-day practice run and verdict, marathon closeout verifier | staged for deletion together with the code they pin — a test is the only thing that kept this bundle in the tree |
Design knowledge extracted from deleted workflows lives in
`docs/design-notes/` (e.g. `backend-rollback.md`), not here.
