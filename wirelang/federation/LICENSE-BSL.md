# Business Source License 1.1

**Licensor:** Callandor GmbH (Falkenstr. 31, 81541 München, Germany;
Amtsgericht München HRB 270414), operating Wakir Labs.

**Licensed Work:** Wakir Wirelang Federation module — the contents of
the `wirelang/federation/` directory of this repository plus the
following sibling files that are part of the Federation-Server
runtime surface:

- `wirelang/identity/federation_resolver.py` (V-908 SPIFFE-ID
  cross-trust-domain resolver),
- `wirelang/cli/marker_stack_reduce.py` (operator marker-stack
  reduction CLI),
- `wirelang/adapters/real_nats_adapter/adapter.py` (live NATS
  JetStream adapter used by the Federation runtime).

The Licensed Work covers multi-org attestation substrate, the
SPIFFE cross-trust-domain bridge, marker-stack composition and
KV-backed reducers, route registries, sequence-number ledgers,
caveat-override export plumbing, the N2 Datalog evaluator, the N3
chain walker, and the capability-attenuation chain verifiers.

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

This is a draft license header following the BSL 1.1 template
published at <https://mariadb.com/bsl11/>. The exact wording of the
Additional Use Grant and the Licensor field is subject to legal
review before any public hosted-service offering is launched.

For terms of the BSL 1.1 itself (rights granted, restrictions,
non-compete clause, conversion mechanism), see the canonical text
at <https://mariadb.com/bsl11/>.

The four-year automatic conversion to Apache 2.0 is a hard,
contractual commitment of the Licensor — not a unilateral promise.
Once a `wirelang/federation/` release is published under this BSL
header, that specific release converts to Apache 2.0 on the Change
Date stated in the release artefact, without further action by the
Licensor.

## Sibling BSL modules

The repository carries sibling BSL 1.1 headers on:

- `wat/` — the Wakir Audit Trail module
  (see [wat/LICENSE-BSL.md](../../wat/LICENSE-BSL.md));
- `infra/spire/federation/provisioner/` — the Wakir Provisioner
  image
  (see [infra/spire/federation/provisioner/LICENSE-BSL.md](../../infra/spire/federation/provisioner/LICENSE-BSL.md));
- `infra/spire/federation/` — the SPIRE Federation server-side
  runtime
  (see [infra/spire/federation/LICENSE-BSL.md](../../infra/spire/federation/LICENSE-BSL.md));
- `infra/spire/agent/` — the SPIRE federated agent runtime
  (see [infra/spire/agent/LICENSE-BSL.md](../../infra/spire/agent/LICENSE-BSL.md)).

Each BSL unit has its own Change Date because they were first
BSL-published on different dates. The `wirelang/federation/` unit
shares its Change Date with the other Phase-2-Federation-BSL units
activated under ADR-0059 on 2026-05-13.

## Foundation-Layer scope

The Foundation-Layer of `wirelang/` (identity bearer, datalog
evaluator core, capability primitives outside the federation tree)
remains Apache-2.0. Only the modules listed under "Licensed Work"
above carry the BSL header. The Brand-Proof verifier
(`wat/anchor/external_verifier/`) remains Apache-2.0 as a
brand-proof-redistributable surface (ADR-0023b).

## Repository licensing layout

The repository root [LICENSE](../../LICENSE) lists the Apache-2.0
default for all directories not explicitly carrying an own header.
BSL-1.1 currently covers `wat/`,
`infra/spire/federation/provisioner/`, `wirelang/federation/`,
`infra/spire/federation/` (excluding the Apache-2.0 Brand-Proof
verifier surface) and `infra/spire/agent/`. CC BY 4.0 covers
documentation where indicated. See the repository
[README](../../README.md) for the consolidated licensing overview.
