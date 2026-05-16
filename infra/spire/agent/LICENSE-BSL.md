This license text is final for this release.

# Business Source License 1.1

**Licensor:** Callandor GmbH (Falkenstr. 31, 81541 München, Germany;
Amtsgericht München HRB 270414), operating Wakir Labs.

**Licensed Work:** Wakir SPIRE federated agent runtime — the
contents of the `infra/spire/agent/` directory of this repository,
including:

- the agent-side federation attestation and reload CLI surface
  (`bin/spire_agent_fed_attest.py`, `bin/spire_agent_fed_reload.py`
  and their console-script wrappers),
- the Quadlet unit files for the SPIRE-Agent federation pod
  (`quadlet/*.container`, `quadlet/*.volume`),
- the Compose recipe for agent-side bring-up
  (`compose/spire-agent-federation.yaml`),
- the SPIRE-Agent federation client configuration
  (`config/spire-agent-wakir.conf`, `config/spire-agent-partner.conf`).

**Additional Use Grant:** Production use of the Licensed Work is
permitted for self-hosting against an operator's own organisational
SPIRE-Federation substrate, *unless* the production use is a
commercial multi-tenant federation-as-a-service offering
substantially competing with the hosted offering operated by Wakir
Labs. Internal use by a single organisation (including its
subsidiaries and contractors operating on its behalf) is permitted
under the BSL header; commercial multi-tenant hosting requires a
separate Wakir-Cloud licence.

**Change Date:** 2030-05-13 (four (4) years after ADR-0059 BSL
activation on 2026-05-13).

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
Once an `infra/spire/agent/` release is published under this BSL
header, that specific release converts to Apache 2.0 on the Change
Date stated in the release artefact, without further action by the
Licensor.

## Sibling BSL modules

The repository carries sibling BSL 1.1 headers on:

- `wat/` — the Wakir Audit Trail module
  (see [`wat/LICENSE-BSL.md`](../../../wat/LICENSE-BSL.md));
- `wirelang/federation/` — the Wakir Wirelang Federation module
  (see [`wirelang/federation/LICENSE-BSL.md`](../../../wirelang/federation/LICENSE-BSL.md));
- `wirelang/persona_engine/` — the Wakir Persona-Engine module
  (see [`wirelang/persona_engine/LICENSE-BSL.md`](../../../wirelang/persona_engine/LICENSE-BSL.md));
- `infra/spire/federation/` — the SPIRE Federation server-side
  runtime
  (see [`infra/spire/federation/LICENSE-BSL.md`](../federation/LICENSE-BSL.md));
- `infra/spire/federation/provisioner/` — the Wakir Provisioner
  image
  (see [`infra/spire/federation/provisioner/LICENSE-BSL.md`](../federation/provisioner/LICENSE-BSL.md));
- `infra/persona-engine/` — the Wakir Persona-Engine container
  image
  (see [`infra/persona-engine/LICENSE-BSL.md`](../../persona-engine/LICENSE-BSL.md)).

Each BSL unit has its own Change Date because they were first
BSL-published on different dates. The `infra/spire/agent/` unit
shares its Change Date with the other Phase-2-Federation-BSL units
activated under ADR-0059 on 2026-05-13.

## Repository licensing layout

The repository root [LICENSE](../../../LICENSE) lists the
Apache-2.0 default for all directories not explicitly carrying an
own header. BSL-1.1 currently covers `wat/` (excluding the
Apache-2.0 Brand-Proof verifier surface), `wirelang/federation/`,
`wirelang/persona_engine/`, `infra/spire/federation/`,
`infra/spire/federation/provisioner/`, `infra/spire/agent/`
(this unit), and `infra/persona-engine/`. CC BY 4.0 covers
documentation where indicated. See the repository
[README](../../../README.md) for the consolidated licensing
overview.
