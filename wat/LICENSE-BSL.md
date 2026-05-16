This license text is final for this release.

# Business Source License 1.1

**Licensor:** Callandor GmbH (Falkenstr. 31, 81541 München, Germany;
Amtsgericht München HRB 270414), operating Wakir Labs.

**Licensed Work:** Wakir Audit Trail (WAT) module — the contents of
the `wat/` directory of this repository, including the hourly Merkle
aggregator, OTS anchor pipeline, and verification CLI server-side
components. The Brand-Proof external verifier
(`wat/anchor/external_verifier/`) is carved out of the Licensed Work
and remains Apache-2.0 (ADR-0023b).

**Additional Use Grant:** Production use of the Licensed Work is
permitted for self-hosting against an operator's own organisational
audit-trail substrate, *unless* the production use is a commercial
multi-tenant audit-trail-as-a-service offering substantially
competing with the hosted offering operated by Wakir Labs. Internal
use by a single organisation (including its subsidiaries and
contractors operating on its behalf) is permitted under the BSL
header; commercial multi-tenant hosting requires a separate
Wakir-Cloud licence.

**Change Date:** 2030-05-07 (four (4) years after ADR-0034 Pfad β
approval 2026-05-06).

**Change License:** Apache License, Version 2.0.

---

## Notice

This license header follows the BSL 1.1 template published at
<https://mariadb.com/bsl11/>.

For terms of the BSL 1.1 itself (rights granted, restrictions,
non-compete clause, conversion mechanism), see the canonical text
at <https://mariadb.com/bsl11/>.

The four-year automatic conversion to Apache 2.0 is a hard,
contractual commitment of the Licensor — not a unilateral promise.
Once a `wat/` release is published under this BSL header, that
specific release converts to Apache 2.0 on the Change Date stated
in the release artefact, without further action by the Licensor.

This module is the first BSL-licensed module in the Wakir Runtime
repository (Phase-1a, ADR-0034 Pfad β). All other directories of
this repository are released under their own license headers
(Apache 2.0 by default; CC BY 4.0 for documentation where
indicated). See the repository root [LICENSE](../LICENSE) and
[README](../README.md) for the full licensing layout.

## Sibling BSL modules

The repository carries sibling BSL 1.1 headers on:

- `wirelang/federation/` — Wakir Wirelang Federation module
  (see [`wirelang/federation/LICENSE-BSL.md`](../wirelang/federation/LICENSE-BSL.md));
- `wirelang/persona_engine/` — Wakir Persona-Engine module
  (see [`wirelang/persona_engine/LICENSE-BSL.md`](../wirelang/persona_engine/LICENSE-BSL.md));
- `infra/spire/federation/` — SPIRE Federation server-side runtime
  (see [`infra/spire/federation/LICENSE-BSL.md`](../infra/spire/federation/LICENSE-BSL.md));
- `infra/spire/federation/provisioner/` — Wakir Provisioner image
  (see [`infra/spire/federation/provisioner/LICENSE-BSL.md`](../infra/spire/federation/provisioner/LICENSE-BSL.md));
- `infra/spire/agent/` — SPIRE federated agent runtime
  (see [`infra/spire/agent/LICENSE-BSL.md`](../infra/spire/agent/LICENSE-BSL.md));
- `infra/persona-engine/` — Wakir Persona-Engine container image
  (see [`infra/persona-engine/LICENSE-BSL.md`](../infra/persona-engine/LICENSE-BSL.md)).

Each BSL unit has its own Change Date because they were first
BSL-published on different dates.
