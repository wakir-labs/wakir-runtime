This license text is final for this release.

# Business Source License 1.1

**Licensor:** Callandor GmbH (Falkenstr. 31, 81541 München, Germany;
Amtsgericht München HRB 270414), operating Wakir Labs.

**Licensed Work:** Wakir Provisioner image — the
`infra/spire/federation/provisioner/` directory of this repository
(Containerfile, hash-pinned wheel manifest, build recipe, and the
published OCI image
`ghcr.io/wakir-labs/wakir-provisioner`) together with the
sandbox-side per-org NATS-KV bucket provisioner driver
`bin/nats_kv_bucket_provision.py` that the image carries as its
runtime workload.

**Additional Use Grant:** Production use of the Licensed Work is
permitted for self-hosting against an operator's own organisational
SPIRE-Federation substrate, *unless* the production use is a
commercial multi-tenant federation-as-a-service or
provisioner-as-a-service offering substantially competing with the
hosted offering operated by Wakir Labs. Internal use by a single
organisation (including its subsidiaries and contractors operating
on its behalf) is permitted under the BSL header; commercial
multi-tenant hosting requires a separate Wakir-Cloud licence.

**Change Date:** 2030-05-13 (four (4) years after the first
BSL-licensed image publication, `wakir-provisioner:0.1.2`).

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
Once a `wakir-provisioner` release is published under this BSL
header, that specific release converts to Apache 2.0 on the
Change Date stated in the release artefact, without further action
by the Licensor.

## Transitive wheel licences

The image pulls a hash-pinned set of third-party Python wheels
during build (see `requirements.txt`). Those wheels ship under
their upstream licences (`nats-py` — Apache-2.0; CPython stdlib —
PSF-2.0; transitive build-time dependencies of the wheel set carry
their own headers). The BSL header on the Licensed Work does NOT
extend to those wheels — they remain governed by their upstream
licences and are reachable via `pip show <pkg>` inside a running
container.

## Sibling BSL modules

The `wat/` directory of this repository carries a sibling BSL 1.1
header with its own Change Date — see `wat/LICENSE-BSL.md`. The
Wakir Provisioner module and the WAT module are independent BSL
units; their Change Dates are independent because they were first
BSL-published on different dates.

## Repository licensing layout

The repository root [LICENSE](../../../../LICENSE) lists the
Apache-2.0 default for all directories not explicitly carrying an
own header. BSL-1.1 currently covers `wat/` and the Wakir
Provisioner unit defined above. CC BY 4.0 covers documentation
where indicated. See the repository [README](../../../../README.md)
for the consolidated licensing overview.
