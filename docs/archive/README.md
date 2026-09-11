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

Design knowledge extracted from deleted workflows lives in
`docs/design-notes/` (e.g. `backend-rollback.md`), not here.
