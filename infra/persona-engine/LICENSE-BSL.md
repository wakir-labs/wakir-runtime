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

This is a draft license header following the BSL 1.1 template
published at <https://mariadb.com/bsl11/>. The exact wording of the
Additional Use Grant and the Licensor field is subject to legal
review before any public hosted-service offering is launched.

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
