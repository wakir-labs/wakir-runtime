# TV-W-1 Identity Pin-Pack (Golden Fixture)

This directory contains the frozen golden fixture for **TV-W-1**, the
first Wirelang test vector defined in
`wirelang/specs/wirelang-tv-strategy.md` §1.

## Contents

- `pin-pack.json` — the canonical pin-pack: nine personas × two curves
  = eighteen derivations along
  `m / 44' / WAKIR_COIN_TYPE' / persona_idx' / spawn_counter'` from the
  BIP-32 test-vector-1 seed (`000102030405060708090a0b0c0d0e0f`).
  Each record carries the secp256k1 / Ed25519 public keys, the
  JCS-SHA-256 of the unsigned DID document, the JCS-SHA-256 of the
  signed AIP document, and the deterministic Ed25519 AIP-document
  signature.

The top-level `pin_pack_sha256` field is SHA-256 of the JCS-canonical
form of the pin-pack body (records + metadata, without the hash slot
itself). It is the single drift-detector for the entire vector.

## Determinism notes

- **Ed25519 (RFC 8032)** is deterministic; the AIP `document_signature`
  is byte-stable across runs and is therefore pinned.
- **ECDSA-secp256k1 in `cryptography.hazmat`** is *not* deterministic
  (see `test_did_document_golden.py` for the existing inverse-
  determinism check). The DID-document `proof` slot is therefore
  excluded from this pin-pack; we pin the SHA-256 of the *unsigned*
  DID-document body instead, which is byte-stable.

## Regeneration

The fixture is regenerated via the documented module CLI:

```
python -m wirelang.tests._tv_w_1_pin_pack_builder
```

This is also the external-regeneration contract checked by acceptance
criterion A5 in `test_tv_w_1_identity_roundtrip.py`.

To compute the pin-pack hash without writing the fixture:

```
python -m wirelang.tests._tv_w_1_pin_pack_builder --check
```

A re-baseline (intentional pin-pack drift) is an explicit engineering
event: re-run the CLI, review the diff, commit on a feature branch.

## Brand-Guide §9 compliance

All persona role-strings are mechanically generated from
`(persona_idx, spawn_counter)` as `tv-w-1-persona-<p>-<s>`. No clear
personal names appear in the fixture or in the inputs.
