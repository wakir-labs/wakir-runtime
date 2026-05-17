<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Licensing

This repository is **mixed-license, BUSL-dominant**. It is the
source-available enterprise substrate of the four-repo Wakir Labs
topology. Two Apache-2.0 sibling repos hold the brand-proof
verifier and the protocol-/spec-layer respectively:

- **`wakir-labs/wakir-verify`** — Apache-2.0 (brand-proof Verifier
  CLI: WAT-Manifest, Merkle-Inclusion, OTS-Anchor). Stand-alone
  consumable. Consolidated per ADR-0062 Cut-1.
- **`wakir-labs/wakir-protocol`** — Apache-2.0 (Code) + CC-BY-4.0
  (Specs, file-level): Wirelang-Spec Layer 0-2, JSON-Schemas,
  Capability-Token-Wrapper, Identity-Substrate. Consolidated per
  ADR-0062 Cut-2.

The Apache foundation snippets that remain inside this repo are
preserved for source-pin reasons (BUSL-Subtree-internal use of
canonical algorithms); they are **mirrored, not authoritative** —
the authoritative copies are in the sibling repos above.

## Path-to-License Map

The authoritative path-to-license map. Each row is enforced by the
`tests/infra/test_licensing_md_state.py` hermetic test suite (every
BSL sub-tree listed below must carry a `LICENSE-BSL.md` file at the
named path; every Apache-2.0 carve-out within a BSL sub-tree must
exist on disk; every Rust workspace crate must default to the
workspace `license = "Apache-2.0"` field).

### Python / runtime tree

| Path | License |
|---|---|
| `wirelang/` except listed BSL modules | Apache-2.0 (mirrored from `wakir-labs/wakir-protocol`) |
| `wat/` except listed Apache-2.0 carve-outs | BUSL-1.1, Change License Apache-2.0 |
| `wat/anchor/external_verifier/` | Apache-2.0 (mirrored from `wakir-labs/wakir-verify` per ADR-0062 Cut-1) |
| `wat/merkle/` Read-Half (`__init__.py`, `aggregator.py`) | Apache-2.0 (mirrored from `wakir-labs/wakir-verify` per ADR-0062 Cut-1) |
| `wirelang/federation/` | BUSL-1.1 |
| `wirelang/persona_engine/` | BUSL-1.1 |

### Infrastructure sub-trees

| Path | License |
|---|---|
| `infra/spire/federation/` | BUSL-1.1 |
| `infra/spire/federation/provisioner/` | BUSL-1.1 (own sub-tree per ADR-0058; carries its own `LICENSE-BSL.md` with Change-Date 2030-05-13) |
| `infra/spire/agent/` | BUSL-1.1 |
| `infra/persona-engine/` | BUSL-1.1 |

### Rust workspace

| Path | License |
|---|---|
| `wirelang-rust/` workspace default | Apache-2.0 (`[workspace.package] license = "Apache-2.0"`) |
| `wirelang-rust/crates/*/` (all crates) | Apache-2.0 (per-crate `license.workspace = true` or explicit `license = "Apache-2.0"`) |

### Documentation, tooling, tests

| Path | License |
|---|---|
| `docs/` specs/runbooks where marked | CC-BY-4.0 |
| `tooling/` | Apache-2.0 unless otherwise marked |
| `tests/` | follows subject under test |

## Adopter Guidance (post-Cut-1/Cut-2)

If you are an adopter of the Wakir methodology and want to integrate
*only* the open surfaces:

- Need a verifier? Use `pip install wakir-verify` (Apache-2.0,
  stand-alone, no Wakir-runtime dependency).
- Need the protocol/spec layer? Use `pip install wakir-protocol`
  (Apache-2.0 + CC-BY-4.0 specs).
- Need the BUSL-1.1 substrate (Federation, Persona-Engine, WAT-
  Pipeline-Server)? Then you are within the scope of this repo and
  the BUSL-1.1 terms apply (Change Date 2030-05-07 / 2030-05-13 per
  module). Internal use by a single organisation is permitted under
  the Additional Use Grant; commercial multi-tenant hosting requires
  a separate Wakir-Cloud licence.

The authoritative per-module license text lives in the `LICENSE-BSL.md`
file at the root of each BUSL-1.1 sub-tree. The `LICENSES/` directory
holds the full canonical text for each license identifier referenced
above (Apache-2.0, BUSL-1.1, CC-BY-4.0), in a layout that is
REUSE-3.0-compliant for downstream license scanners.

For background on the phased BSL roll-out and the strategic rationale,
see `decisions/0034-repo-lizenz-strategie.md` and
`decisions/0059-phase-2-federation-bsl-aktivierung.md`.
