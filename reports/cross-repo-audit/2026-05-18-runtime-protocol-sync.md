<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Cross-repo sync audit — 2026-05-18

Tag-42 Reza Cross-Repo-Sync-Audit between `wakir-runtime`
(BUSL-dominant) and `wakir-protocol` (Apache-2.0 + CC-BY-4.0).

## Audit baselines

- Runtime root: `/var/home/fred/AI-Corp/.worktree-reza-tag42-cross-repo-audit-runtime`
- Runtime HEAD: `64b1c170418d`
- Protocol root: `/tmp/wakir-protocol-tag42`
- Protocol HEAD: `9eca1e2d4b5b`
- Enforce mode: `False`
- Allowlist status: `ok`

## Mirror-pair drift table (substance class 1-3)

| Status | Class | Runtime | Protocol | r-SHA | p-SHA |
|---|---|---|---|---|---|
| DRIFT | layer-0-schema | `wirelang/schemas/layer-0-transport.json` | `wakir_protocol/schemas/layer-0-transport.json` | `714f9d42b8fc` | `5e95e26c127b` |
| ok | layer-1-schema | `wirelang/schemas/layer-1-wire.json` | `wakir_protocol/schemas/layer-1-wire.json` | `15a8f97f8925` | `15a8f97f8925` |
| DRIFT | layer-2-schema | `wirelang/schemas/layer-2-semantic.json` | `wakir_protocol/schemas/layer-2-semantic.json` | `c0f54b92f8ab` | `c9519af54347` |
| DRIFT | layer-3-schema | `wirelang/schemas/layer-3-capability-token.json` | `wakir_protocol/schemas/layer-3-capability-token.json` | `2b4eb8d067f5` | `4d8e064c8133` |
| DRIFT | aip | `wirelang/schemas/aip-document.json` | `wakir_protocol/schemas/aip-document.json` | `cec984969de3` | `0219e3c0c39a` |
| ok | aip | `wirelang/identity/aip_document.py` | `wakir_protocol/identity_substrate/aip_document.py` | `ad520986ab69` | `ad520986ab69` |
| ok | aip | `wirelang/identity/dns_anchor.py` | `wakir_protocol/identity_substrate/dns_anchor.py` | `9e3faabca58e` | `9e3faabca58e` |
| ok | capability | `wirelang/schemas/datalog-caveat.json` | `wakir_protocol/schemas/datalog-caveat.json` | `dfe35884bbb9` | `dfe35884bbb9` |
| DRIFT | capability | `wirelang/schemas/federation-trust-document.json` | `wakir_protocol/schemas/federation-trust-document.json` | `d1b09c7bc815` | `b1f4cc169a08` |
| DRIFT | capability | `wirelang/canonical/caveat_set.py` | `wakir_protocol/canonical/caveat_set.py` | `a2155411ef68` | `f7d391fab9e6` |

### Mirror-pair tally

- ok: 4
- drift (un-allowlisted): 6
- drift (allowlisted): 0
- missing on either side: 0

## ADR-0066 Welle-Substanz consistency (class 4)

| Welle | Smoke | Runbook | Validation WF | Modules | Protocol mention | Status |
|---|---|---|---|---|---|---|
| 1 | Y | Y | Y | Y | — | consistent-runtime-only |
| 2 | Y | Y | Y | Y | — | consistent-runtime-only |
| 3 | Y | Y | Y | Y | — | consistent-runtime-only |
| 4 | Y | Y | Y | Y/Y | — | consistent-runtime-only |
| 5 | Y | Y | Y | Y/Y | — | consistent-runtime-only |
| 6 | Y | Y | Y | Y | — | consistent-runtime-only |
| 7 | Y | Y | Y | Y | — | consistent-runtime-only |

### Welle tally

- ok (runtime-complete + protocol-mentioned): 0
- consistent (runtime-complete, protocol doc absent): 7
- protocol-doc-missing-mention: 0
- incomplete runtime triad: 0

## Recommended mirror-sync actions

- Resolve 6 un-allowlisted drift item(s) by
  either lifting the runtime change into the protocol
  repo (1-way mirror sync) or admitting an allowlist
  entry in `.cross-repo-drift-allowlist.yaml` with a
  named reason and follow-up reference.

## Phase-3-Marathon cross-repo readiness

- Status: **BLOCKED** until the recommended actions above
  close the cross-repo deltas. Re-run this audit after
  each remediation PR; record the new clean baseline in
  `docs/operations/cross-repo-drift-mirror-pair-status.md`.

## Cross-references

- ADR-0062 Cut-2 protocol-substance classification
  (`docs/decisions/cut2-protocol-substance-classification.md`)
- ADR-0066 Welle-Substanz roadmap
- `.github/workflows/cross-repo-drift-audit.yml` (CI tripwire,
  audit-only at the time of this report)
- `.cross-repo-drift-allowlist.yaml` (CI allowlist)
- `docs/operations/cross-repo-drift-runbook.md`
- `docs/operations/cross-repo-drift-mirror-pair-status.md`

— Reza
