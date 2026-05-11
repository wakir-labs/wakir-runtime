<!--
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
SPDX-License-Identifier: Apache-2.0
-->

# Zone-M TV-4 cross-component test-vector set

Status: Phase-2 Welle-27 (2026-05-11).
Owner: QA (`agents-workspaces/qa/`).
Boundary partner: `dev-engineering` (Tomas, 31-vector substrate),
`reza` (Wirelang.identity.aip_signing), `pengine` (Selin, capability-
token producer).

## Provenance

This vector file is the QA-owned counterpart to the dev-engineering-
owned 31-vector conformance set at
`tooling/external-verifier-ajv/test-vectors.json`. The Tomas set
pins **schema correctness** as a v1-implementer floor. The TV-4 Zone-M
set pins **cross-component-boundary surface** that the schema accepts
or rejects -- i.e. the shape contract between WAT manifests and
neighbouring components (Wirelang signature slot, Pengine capability
tokens, schema-version-enum forward-compat).

The two files coexist intentionally:

- `tooling/external-verifier-ajv/test-vectors.json` is the public-
  facing adoption surface for third-party verifier implementers
  (referenced by `docs/external-verifier-conformance.md`).
- `tests/fixtures/zone-m-tv4/zone-m-tv4-vectors.json` is the QA-
  internal cross-component coverage surface for Zone-M boundary
  pins -- not part of the third-party conformance contract but
  driven through the **same three reference validators** so the
  schema-correctness invariant transitively holds.

## Vector-set sha256

Sprint-6-Tag-2 stand (initial Zone-M floor of 8 vectors):

```
33e9f1cb36ecfaea09b66e618564ff7b3cdb86167f4c08be52573e6299df0ceb
```

Recompute on every box that mutates the file:

```sh
sha256sum tests/fixtures/zone-m-tv4/zone-m-tv4-vectors.json
```

## Schema annotations carried by each vector

Each TV-4 vector adds two annotation fields on top of the
`name`/`expect`/`manifest` shape required by the parity driver:

| Field         | Purpose                                                          |
|---------------|------------------------------------------------------------------|
| `zone_m_axis` | Which cross-component boundary this vector pins (persona x persona). |
| `boundary`    | Human-readable boundary description -- why this vector exists.   |

Both fields are ignored by the parity driver (`name`/`expect`/
`manifest` are the only fields it consumes), but the QA parity test
(`tests/wat/test_zone_m_tv4_parity.py`) asserts both are present on
every vector -- the annotations are mandatory in this directory.

## Coverage surface (initial 8 vectors)

| # | Vector name                                       | Boundary axis                                              | Verdict |
|---|---------------------------------------------------|------------------------------------------------------------|---------|
| 1 | zone-m-tv4-signature-slot-well-formed             | WAT x Wirelang.aip_signing (positive)                       | accept  |
| 2 | zone-m-tv4-signature-alg-not-ed25519              | WAT x Wirelang.aip_signing (closed alg-enum)                | reject  |
| 3 | zone-m-tv4-signature-kid-empty                    | WAT x Wirelang.aip_signing x AIP-doc.public_keys            | reject  |
| 4 | zone-m-tv4-signature-hex-off-by-one               | WAT x Wirelang.aip_signing (hex-128 boundary)               | reject  |
| 5 | zone-m-tv4-signature-additional-property          | WAT x Wirelang.aip_signing (closed-shape)                   | reject  |
| 6 | zone-m-tv4-multi-event-distinct-caprefs           | WAT x Pengine.capability-token (Selin)                      | accept  |
| 7 | zone-m-tv4-version-v2-with-v1-shape               | WAT x Wirelang.schema-version (forward-compat)              | accept  |
| 8 | zone-m-tv4-signature-block-missing-required-alg   | WAT x Wirelang.aip_signing (required-field)                 | reject  |

Floor: 6 vectors (raised by the parity test); current: 8. Sprint-7+
expansion adds the next boundary surface (e.g. v2-multi-cap-token
manifest schema once it lands, or capability-token-revocation
hash-shape once Reza's Sprint-6 Tag-2 publisher CLI revoke-path
clears).

## Running the TV-4 parity sweep

```sh
# From a clean repo clone:
pip install jsonschema fastjsonschema
(cd tooling/external-verifier-ajv && npm install)

# TV-4-only three-way parity (absolute path, mirrors the Tomas driver):
python scripts/external_verifier_validation.py \
  --vectors "$(pwd)/tests/fixtures/zone-m-tv4/zone-m-tv4-vectors.json"

# Or via pytest (recommended -- skip-aware on missing libraries):
pytest tests/wat/test_zone_m_tv4_parity.py -v
```

Expected footer:

```
cross-tool parity OK (8 vectors, 3 validators: ajv, python-fastjsonschema, python-jsonschema)
```

## Cross-Review trigger

Zone-M coverage changes (new boundary axes, especially under
WAT x Pengine and WAT x Wirelang) require coordination with:

- **Tomas** (WAT-owner, schema-file-owner).
- **Reza** (Wirelang schema-file owner; aip_signing shape contract;
  capability-token / publisher schema co-owner).
- **Selin** (Pengine; capability-token producer-side semantics).

Cross-Review-Spawns are CTO-Hand (Mira-coordinated). This README
documents the trigger surface; Welle-27 box-acceptance-doku names
the specific files needing co-review.

-- Amara
