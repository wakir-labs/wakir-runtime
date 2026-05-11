# wat-tv2-real-signed -- Aggregator-signed TV-2 sub-cohort

This directory holds the Aggregator-signed Variants of the
stock ``../wat-tv2-real/`` TV-2 hour-receipt cohort. Pre-baking
the signed manifests on-disk is the Sprint-6-Tag-5 simplification
of the verifier test substrate: tests no longer need to hand-
sign manifest copies on the hot path; they consume the
checked-in signed manifests directly.

## Demo key material

These fixtures are signed with a doc-pinned demo Ed25519 seed.
The seed is **NOT a production key** -- it is published below
and is used only for fixture-build determinism.

- Private seed (hex, 32 bytes): ``00112233445566778899aabbccddeeff00112233445566778899aabbccddeeff``
- Public key (hex, 32 bytes): ``3ccd241cffc9b3618044b97d036d8614593d8b017c340f1dee8773385517654b``
- Key identifier (``kid``): ``wat-tv2-fixture-demo-key``
- Signature algorithm: ``Ed25519`` (RFC 8032)

Any party can re-derive the public key from the seed via the
``cryptography`` Python package or any conformant Ed25519
implementation, and re-verify every signed manifest in this
directory end-to-end.

## Cohort contents

- ``2026-05-27T00``
- ``2026-05-27T01``
- ``2026-05-27T02``
- ``2026-05-27T03``

Each hour-slot directory carries:

- ``manifest.json`` -- the Aggregator-signed manifest.
- ``root.bin`` -- byte-identical copy of the stock cohort's
  receipt root file.
- ``root.bin.ots`` -- byte-identical copy of the stock cohort's
  OpenTimestamps anchor proof.

The ``root.bin`` and ``root.bin.ots`` files are byte-identical
copies of the stock cohort. The Merkle root in each signed
manifest matches the stock cohort's Merkle root (deterministic
Aggregator contract); the OTS-anchor check verifies against
the same bytes the original receipt anchored.

## Regeneration

From the repo root::

    python3 scripts/wat-tv2-fixture-regenerate-signed.py

The script is idempotent: re-running it produces byte-identical
output. Determinism is enforced by the doc-pinned demo seed
above and by the canonical JCS-signing primitive in
``wat.identity.manifest_signing``.

## Test consumption

See ``tests/wat/test_tv2_real_signed_fixture.py`` for the
verifier-side regression pins.
