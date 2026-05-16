This license text is final for this release.

# Business Source License 1.1

**Licensor:** Callandor GmbH (Falkenstr. 31, 81541 München, Germany;
Amtsgericht München HRB 270414), operating Wakir Labs.

**Licensed Work:** Wakir Persona-Engine image — the
`infra/persona-engine/` directory of this repository (Containerfile,
stub binary, build recipe, and the published OCI image
`ghcr.io/wakir-labs/wakir-persona-engine`).

**Additional Use Grant:** Production use of the Licensed Work is
permitted for self-hosting against an operator's own organisational
persona-engine substrate, *unless* the production use is a
commercial multi-tenant persona-engine-as-a-service offering
substantially competing with the hosted offering operated by Wakir
Labs. Internal use by a single organisation (including its
subsidiaries and contractors operating on its behalf) is permitted
under the BSL header; commercial multi-tenant hosting requires a
separate Wakir-Cloud licence.

**Change Date:** 2030-05-15 (four (4) years after the first
BSL-licensed image publication, `wakir-persona-engine:0.1.0-pilot`).

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
Once a `wakir-persona-engine` release is published under this BSL
header, that specific release converts to Apache 2.0 on the
Change Date stated in the release artefact, without further action
by the Licensor.

## Transitive component licences

The `0.1.0-pilot` substrate-stub image carries CPython stdlib only
(no third-party wheels). CPython ships under the Python Software
Foundation License Version 2 (PSF-2.0); the stdlib licence is
unaffected by the BSL header on the image as a whole and remains
reachable via `python3 --version` inside a running container.

The Sprint-Pengine-8 successor image (`0.2.0-pilot` or later) will
carry `nats-py` (Apache-2.0) and `cryptography` (Apache-2.0 / BSD)
in addition to the stdlib; per-wheel licence text will ship in the
wheels themselves and be reachable via `pip show <pkg>` inside a
running container. The BSL header on the image as a whole does not
extend to those transitive wheels.

## Sibling BSL modules

The repository carries sibling BSL 1.1 headers on:

- `wat/` — the Wakir Audit Trail module
  (see [`wat/LICENSE-BSL.md`](../../wat/LICENSE-BSL.md));
- `wirelang/federation/` — the Wakir Wirelang Federation module
  (see [`wirelang/federation/LICENSE-BSL.md`](../../wirelang/federation/LICENSE-BSL.md));
- `wirelang/persona_engine/` — the Wakir Persona-Engine module
  (see [`wirelang/persona_engine/LICENSE-BSL.md`](../../wirelang/persona_engine/LICENSE-BSL.md));
- `infra/spire/federation/` — the SPIRE Federation server-side
  runtime
  (see [`infra/spire/federation/LICENSE-BSL.md`](../spire/federation/LICENSE-BSL.md));
- `infra/spire/federation/provisioner/` — the Wakir Provisioner
  image
  (see [`infra/spire/federation/provisioner/LICENSE-BSL.md`](../spire/federation/provisioner/LICENSE-BSL.md));
- `infra/spire/agent/` — the SPIRE federated agent runtime
  (see [`infra/spire/agent/LICENSE-BSL.md`](../spire/agent/LICENSE-BSL.md)).

Each BSL unit has its own Change Date because they were first
BSL-published on different dates.

## Repository licensing layout

The repository root [LICENSE](../../LICENSE) lists the Apache-2.0
default for all directories not explicitly carrying an own header.
BSL-1.1 currently covers `wat/` (excluding the Apache-2.0
Brand-Proof verifier surface), `wirelang/federation/`,
`wirelang/persona_engine/`, `infra/spire/federation/`,
`infra/spire/federation/provisioner/`, `infra/spire/agent/`, and
`infra/persona-engine/` (this unit). CC BY 4.0 covers documentation
where indicated. See the repository [README](../../README.md) for
the consolidated licensing overview.
