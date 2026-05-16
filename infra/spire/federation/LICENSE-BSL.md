This license text is final for this release.

# Business Source License 1.1

**Licensor:** Callandor GmbH (Falkenstr. 31, 81541 München, Germany;
Amtsgericht München HRB 270414), operating Wakir Labs.

**Licensed Work:** Wakir SPIRE Federation server-side runtime — the
contents of the `infra/spire/federation/` directory of this
repository, including:

- the Bundle-Export / Bundle-Import / health / metrics CLI surface
  (`bin/spire_fed_bundle.py`, `bin/spire_fed_bundle_rotator.py`,
  `bin/spire_fed_health.py`, `bin/spire_fed_metrics.py` and their
  console-script wrappers),
- the Quadlet unit files for the SPIRE-Server federation pod
  (`quadlet/*.container`, `quadlet/*.volume`, `quadlet/*.network`),
- the Compose recipe for federation bring-up
  (`compose/spire-federation.yaml`),
- the SPIRE-Server federation server configuration
  (`config/spire-server-wakir.conf`, `config/spire-server-partner.conf`),
- the Proxmox bring-up bundle scripts
  (`proxmox/build-bundle.sh`, `proxmox/resolve-image-pins.sh`),
- the one-shot pilot bring-up wrapper
  (`wakir-pilot-bootstrap.sh`).

In addition, the following Federation-Substanz-adjacent operator
tooling lives outside `infra/spire/federation/` but is governed by
this licence file, because its sole purpose is to observe and
verify the Federation-Server live substrate:

- `bin/proxmox-bringup-smoke` — Operator-Hand Self-Verify suite for
  the Pilot-VM bring-up. Re-licensed Apache-2.0 -> BSL 1.1 in
  Sprint-9 Tag-6 (Pilot-VM live-bring-up #2, 2026-05-14).

The Wakir Provisioner image, sitting in the
`infra/spire/federation/provisioner/` subdirectory, has its own
BSL header (see
[provisioner/LICENSE-BSL.md](provisioner/LICENSE-BSL.md)) and is
governed by that header rather than this one.

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
Once an `infra/spire/federation/` release is published under this
BSL header, that specific release converts to Apache 2.0 on the
Change Date stated in the release artefact, without further action
by the Licensor.

## Sibling BSL modules

The repository carries sibling BSL 1.1 headers on:

- `wat/` — the Wakir Audit Trail module
  (see [`wat/LICENSE-BSL.md`](../../../wat/LICENSE-BSL.md));
- `wirelang/federation/` — the Wakir Wirelang Federation module
  (see [`wirelang/federation/LICENSE-BSL.md`](../../../wirelang/federation/LICENSE-BSL.md));
- `wirelang/persona_engine/` — the Wakir Persona-Engine module
  (see [`wirelang/persona_engine/LICENSE-BSL.md`](../../../wirelang/persona_engine/LICENSE-BSL.md));
- `infra/spire/federation/provisioner/` — the Wakir Provisioner
  image
  (see [`provisioner/LICENSE-BSL.md`](provisioner/LICENSE-BSL.md));
- `infra/spire/agent/` — the SPIRE federated agent runtime
  (see [`infra/spire/agent/LICENSE-BSL.md`](../agent/LICENSE-BSL.md));
- `infra/persona-engine/` — the Wakir Persona-Engine container
  image
  (see [`infra/persona-engine/LICENSE-BSL.md`](../../persona-engine/LICENSE-BSL.md)).

Each BSL unit has its own Change Date because they were first
BSL-published on different dates. The `infra/spire/federation/`
unit shares its Change Date with the other Phase-2-Federation-BSL
units activated under ADR-0059 on 2026-05-13.

## Brand-Proof scope carve-out

The Brand-Proof external verifier (`wat/anchor/external_verifier/`)
remains Apache-2.0 as a brand-proof-redistributable surface
(ADR-0023b). The `infra/spire/federation/` tree does not currently
carry any Brand-Proof carve-out; the entire subtree (excluding the
provisioner sibling unit) is BSL.

## Repository licensing layout

The repository root [LICENSE](../../../LICENSE) lists the
Apache-2.0 default for all directories not explicitly carrying an
own header. BSL-1.1 currently covers `wat/` (excluding the
Apache-2.0 Brand-Proof verifier surface), `wirelang/federation/`,
`wirelang/persona_engine/`, `infra/spire/federation/` (this unit),
`infra/spire/federation/provisioner/`, `infra/spire/agent/`, and
`infra/persona-engine/`. CC BY 4.0 covers documentation where
indicated. See the repository [README](../../../README.md) for the
consolidated licensing overview.
