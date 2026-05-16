<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Licensing

This repository is mixed-license.

| Path | License |
|---|---|
| `wirelang/` except listed BSL modules | Apache-2.0 |
| `wat/` except listed Apache-2.0 carve-outs | BUSL-1.1, Change License Apache-2.0 |
| `wat/anchor/external_verifier/` | Apache-2.0 (brand-proof verifier, consolidated to `wakir-labs/wakir-verify` per ADR-0062 Cut-1) |
| `wat/merkle/` Read-Half (`__init__.py`, `aggregator.py`) | Apache-2.0 (re-classified per ADR-0062 Cut-1, brand-proof Merkle inclusion check) |
| `wirelang/federation/` | BUSL-1.1 |
| `wirelang/persona_engine/` | BUSL-1.1 |
| `infra/spire/federation/` | BUSL-1.1 |
| `infra/spire/agent/` | BUSL-1.1 |
| `infra/persona-engine/` | BUSL-1.1 |
| `docs/` specs/runbooks where marked | CC-BY-4.0 |
| `tooling/` | Apache-2.0 unless otherwise marked |
| `tests/` | follows subject under test |

The authoritative per-module license text lives in the `LICENSE-BSL.md`
file at the root of each BUSL-1.1 sub-tree. The `LICENSES/` directory
holds the full canonical text for each license identifier referenced
above (Apache-2.0, BUSL-1.1, CC-BY-4.0), in a layout that is
REUSE-3.0-compliant for downstream license scanners.

For background on the phased BSL roll-out and the strategic rationale,
see `decisions/0034-repo-lizenz-strategie.md` and
`decisions/0059-phase-2-federation-bsl-aktivierung.md`.
