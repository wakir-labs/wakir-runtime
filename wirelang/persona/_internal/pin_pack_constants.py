# SPDX-License-Identifier: Apache-2.0
"""V-907 9-vector pin-pack constants (Phase-1b Sprint-1 Tag-2).

These are the frozen JCS-SHA-256 hex tails for the nine canonical
test fixtures under
``wirelang/tests/fixtures/persona_definitions/v{N}-persona-*.md``.

Pattern mirrors the AIP-document-hash and capability-token-hash
pin packs from the WAT-eng tree. Any drift in JCS canonicalisation,
in the canonical-subset extractor, or in the YAML front-matter of a
fixture will break a pin assertion at byte granularity.

Vector layout
-------------

- v1 — ceo baseline (frontmatter + body)
- v2 — wat-eng baseline (cross-review zone K + G)
- v3 — identity-eng baseline (cross-review zone L + G)
- v4 — ceo with description front-matter edit (M-1 in-hash mutation)
- v5 — ceo with body-only edit (M-3 OUT-of-hash; pin EQUAL to v1)
- v6 — ceo with extra cross_review_zone (M-2 in-hash mutation)
- v7 — V-908 federation stub: NOT a file; the empty-string sentinel
       lives in :data:`PERSONA_EMPTY_REF_SENTINEL` and is not stored
       in this hex-pin pack.
- v8 — self-migration source, schema_version=persona-v0 (REJECTED:
       no hex pin; the test asserts the rejection class instead).
- v9 — self-migration target, schema_version=persona-v1.

Pins are populated by the Tag-2 bootstrap test
``test_pin_pack_constants_match_fixtures`` once fixtures are
in tree. The values below are the actually-computed hex tails
captured at that bootstrap step; updating any fixture front-matter
forces a re-pin sweep.
"""

from __future__ import annotations

from typing import Final


PERSONA_HASH_PIN_V1: Final[str] = (
    "sha256:ef6915339c7e11df38a0d56d21e2ea02b828223bf2fe3f4bc12710a239349fff"
)
PERSONA_HASH_PIN_V2: Final[str] = (
    "sha256:e9eddc382d6601bdcc8b862eccebf9348223142fbc8c644d7f7aa8478e9d0220"
)
PERSONA_HASH_PIN_V3: Final[str] = (
    "sha256:3f1f9ef37f98aa51ca4bba96a487a2246f126ed79f53d7de0fd0e052805c35d9"
)
PERSONA_HASH_PIN_V4: Final[str] = (
    "sha256:b81ee5e6702ff2cb3dd6f6a2a9f2b26e3471d6768d6d95a4d30fb5227c2a1273"
)
#: v5 SHARES the v1 pin by design (body-edit, out-of-hash invariant).
PERSONA_HASH_PIN_V5: Final[str] = PERSONA_HASH_PIN_V1
PERSONA_HASH_PIN_V6: Final[str] = (
    "sha256:ab7a84a46ccd8d9f3b143d557bcf5ba00900343c4f649c2b6f909b1f55ab5a4e"
)
PERSONA_HASH_PIN_V9: Final[str] = (
    "sha256:0f298894204e6117e42ad7073b7a3af8ada1851de74d585fc5cb4c4d70e1d793"
)

#: Self-migration target pin: hash of the canonical subset produced
#: by ``V0ToV1Step.apply`` on the v8 fixture (Sprint-2 Tag-1 S2-T1-06).
#:
#: By design EQUAL to :data:`PERSONA_HASH_PIN_V9` — the v8 and v9
#: fixtures share every front-matter key except ``schema_version``,
#: and the migration step lifts exactly that key. Pinned as its own
#: constant so a future converter regression (e.g. accidental key
#: re-ordering, default injection drift) breaks an explicit assertion
#: and not just an indirect equality.
PERSONA_HASH_PIN_V8_MIGRATED_TO_V1: Final[str] = PERSONA_HASH_PIN_V9


#: Self-migration target pin (V9-to-V2): hash of the canonical subset
#: produced by ``V1ToV2Step.apply`` on the v9 fixture (Phase-1b
#: Sprint-3 Tag-3, V10-Migration-Pfad). The V9-to-V2 lift is a
#: ``schema_version`` const flip from ``persona-v1`` to ``persona-v2``;
#: every other canonical-subset byte is preserved. Because the
#: canonical-subset *includes* ``schema_version``, this pin is **not**
#: equal to :data:`PERSONA_HASH_PIN_V9` (Tag-1-Sketch §3 explicit
#: design choice). The hex tail below was computed from the
#: ``v9-persona-framework-native.md`` fixture during Sprint-3 Tag-3
#: implementation; updating the v9 fixture front-matter forces a
#: re-pin sweep here.
PERSONA_HASH_PIN_V9_MIGRATED_TO_V2: Final[str] = (
    "sha256:f719fce4bedd8522874ae214ec2f982ef87964b535ca368134b3636207eb6669"
)

#: Self-migration target pin (V8-via-chain-to-V2): hash of the
#: canonical subset produced by chaining
#: ``[V0ToV1Step(), V1ToV2Step()]`` on the v8 fixture. By construction
#: EQUAL to :data:`PERSONA_HASH_PIN_V9_MIGRATED_TO_V2` — the v8 and v9
#: fixtures share every canonical-subset key except ``schema_version``,
#: and the chain endpoint sets ``schema_version=persona-v2`` either
#: way. This is the **M-1 (linear-chain) direct-anchor** that the
#: Sprint-2 M-Konsens-Marker companion memo flagged as currently
#: indirect. Pinning it explicitly so a chain-resolver regression
#: (e.g. accidental short-circuit at v1) trips an explicit assertion
#: and not just an indirect equality.
PERSONA_HASH_PIN_V8_MIGRATED_TO_V2: Final[str] = PERSONA_HASH_PIN_V9_MIGRATED_TO_V2
