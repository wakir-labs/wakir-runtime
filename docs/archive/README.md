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
| `evidence/audits/persona-engine-0-5-3-production-readiness-2026-05-19.md` | Persona-Engine 0.5.3 production-readiness audit (D1–D7 verdicts) | release evidence for the shipped 0.5.3 engine; pinned by `wirelang/tests/persona_engine/test_tag63_production_readiness_audit.py` and the engine-version-drift allowlist |
| `evidence/audits/persona-engine-0-5-2-production-readiness-2026-05-19.md` | Persona-Engine 0.5.2-final-pre-cutover production-readiness audit (seven dimensions) | predecessor release evidence for the 0.5.3 audit; pinned by `wirelang/tests/persona_engine/test_tag56_production_readiness_audit.py` |
| `evidence/audits/adr-spec-compliance-audit-2026-05-19.md` | ADR ↔ spec compliance audit (drift summary per ADR) | basis of the six path errata below; pinned by `wirelang/tests/test_adr_spec_compliance_audit_tag54.py` |
| `evidence/decisions/adr-errata-path-typo-fixes.md` | Errata addendum ERR-S1..S6 for path typos in accepted ADRs | records corrections to accepted decision records; pinned by `wirelang/tests/test_adr_errata_tag55.py` |
| `evidence/decisions/spiffe-jwt-svid-identity-sketch.md` | Phase-2 design sketch for the SPIFFE/SPIRE JWT-SVID container identity (trust-domain format, SPIFFE-ID shape, NATS JWT refresh pattern) | superseded by the shipped identity substrate; still the only written record of why the ID components look the way they do, cross-referenced from `docs/nats-jwt-auth-phase-2-4.md` |
| `evidence/decisions/capability-token-layer-snapshot.md` | Point-in-time snapshot of the AIP + Biscuit capability-token layer (module inventory, gap list) | superseded implementation-status record, kept until the capability-token spec carries the same inventory |
| `evidence/decisions/doppelbetrieb-bridge-smoke-acceptance.md` | Acceptance rationale for the dual-operation federation bridge smoke gate | records why the two-emitter smoke shape was accepted |
| `evidence/decisions/anthropic-prompt-caching-phase-2a.md` | Delivery record for the prompt-caching payload builder and telemetry (phase 2a) | closed delivery note, superseded by the shipped module and its tests |
| `evidence/decisions/phase-3-nodeattestor-migration.md` | Tracking note for the planned `x509pop` NodeAttestor migration | historic planning note; phase 3 is complete, the migration was not executed |
| `dead-dashboards/` (5 files) | Grafana dashboards and alert definitions whose panels query metrics no longer produced by any script: the cutover-morning verdict tile, the cross-wave coordination board, the wave-status board, the per-wave trend heatmap and the migration-marathon SLO board | staged for deletion, not evidence — the migration they observed is complete and their producers are gone. Recoverable from tag `archive/pre-phase-4` |

Design knowledge extracted from deleted workflows lives in
`docs/design-notes/` (e.g. `backend-rollback.md`), not here.
