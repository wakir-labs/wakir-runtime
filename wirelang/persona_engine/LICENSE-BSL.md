This license text is final for this release.

# Business Source License 1.1

**Licensor:** Callandor GmbH (Falkenstr. 31, 81541 München, Germany;
Amtsgericht München HRB 270414), operating Wakir Labs.

**Licensed Work:** Wakir Persona-Engine module — the contents of the
`wirelang/persona_engine/` directory of this repository, including
the engine runtime (`engine.py`, `engine_async.py`), the lifecycle
state machine (`lifecycle_state_machine.py`), the bridge audit
writer (`bridge_audit_writer.py`), the despawn-clean workflow
(`despawn_clean.py`), the drill scheduler (`drill_scheduler.py`),
the LLM call shim (`llm_call_shim.py`), the migration runner
(`migrate_version.py`), the NATS subscribe loop
(`nats_subscribe_loop.py`), the observability surface
(`observability.py`), the recovery workflow (`recovery_workflow.py`),
the state-backing layer (`state_backing.py`), the SVID workload
identity client (`svid_workload_identity.py`), the V-907 verifier
(`v907_verify.py`), the workload-API protobuf shim
(`_workload_api_pb2_minimal.py`), and the persona CLI (`cli.py`).

**Additional Use Grant:** Production use of the Licensed Work is
permitted for self-hosting against an operator's own organisational
persona-engine substrate, *unless* the production use is a
commercial multi-tenant persona-engine-as-a-service offering
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
Once a `wirelang/persona_engine/` release is published under this
BSL header, that specific release converts to Apache 2.0 on the
Change Date stated in the release artefact, without further action
by the Licensor.

## Sibling BSL modules

The repository carries sibling BSL 1.1 headers on:

- `wat/` — the Wakir Audit Trail module
  (see [`wat/LICENSE-BSL.md`](../../wat/LICENSE-BSL.md));
- `wirelang/federation/` — the Wakir Wirelang Federation module
  (see [`wirelang/federation/LICENSE-BSL.md`](../federation/LICENSE-BSL.md));
- `infra/spire/federation/` — the SPIRE Federation server-side
  runtime
  (see [`infra/spire/federation/LICENSE-BSL.md`](../../infra/spire/federation/LICENSE-BSL.md));
- `infra/spire/federation/provisioner/` — the Wakir Provisioner
  image
  (see [`infra/spire/federation/provisioner/LICENSE-BSL.md`](../../infra/spire/federation/provisioner/LICENSE-BSL.md));
- `infra/spire/agent/` — the SPIRE federated agent runtime
  (see [`infra/spire/agent/LICENSE-BSL.md`](../../infra/spire/agent/LICENSE-BSL.md));
- `infra/persona-engine/` — the Wakir Persona-Engine container
  image
  (see [`infra/persona-engine/LICENSE-BSL.md`](../../infra/persona-engine/LICENSE-BSL.md)).

Each BSL unit has its own Change Date because they were first
BSL-published on different dates. The `wirelang/persona_engine/`
unit shares its Change Date with the other Phase-2-Federation-BSL
units activated under ADR-0059 on 2026-05-13.

## Foundation-Layer scope

The Foundation-Layer of `wirelang/` (identity bearer, datalog
evaluator core, capability primitives outside the persona-engine
and federation subtrees) remains Apache-2.0. Only the modules
listed under "Licensed Work" above carry the BSL header. The
Brand-Proof verifier (`wat/anchor/external_verifier/`) remains
Apache-2.0 as a brand-proof-redistributable surface (ADR-0023b).

## Repository licensing layout

The repository root [LICENSE](../../LICENSE) lists the Apache-2.0
default for all directories not explicitly carrying an own header.
BSL-1.1 currently covers `wat/`, `wirelang/federation/`,
`wirelang/persona_engine/` (this unit),
`infra/spire/federation/provisioner/`, `infra/spire/federation/`,
`infra/spire/agent/`, and `infra/persona-engine/`. CC BY 4.0 covers
documentation where indicated. See the repository
[README](../../README.md) for the consolidated licensing overview.
