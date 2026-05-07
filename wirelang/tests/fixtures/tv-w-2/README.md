# TV-W-2 Capability-Token Multi-Step Pin-Pack (Golden Fixture)

This directory contains the frozen golden fixture for **TV-W-2**, the
second Wirelang test vector defined in
`wirelang/specs/wirelang-tv-strategy.md` §2 and pin-stabilised by
`wirelang/specs/datalog-caveat-vocabulary-phase-2.md` §6 (the §4-CSC
Caveat-Set Canonicalisation Rule plus the TV-W-2 Pin-Stability
Guarantee).

## Contents

- `pin-pack.json` — the canonical pin-pack containing:
  - **Chain projection.** Authority block (Block 0) plus two append
    blocks (Block 1 scope-narrowing, Block 2 rate-limited) plus a
    sealing block. Each block carries its JCS-canonical payload, its
    Ed25519 signature, and its JCS-SHA-256 block hash.
  - **Verifier traces.** Three traces, one per presentation context
    α / β / γ, each carrying:
    - `block_hashes` — JCS-SHA-256 of each block payload.
    - `caveat_set_hashes` — SHA-256 of §4-CSC canonical form of each
      block's caveat-set.
    - `verify_status` — `accept` for α, `reject` for β/γ.
    - `verify_reason` — canonical reason string (`null` on accept,
      `time-bound-violated` for β, `audience-pattern-mismatch` for γ).
    - `next_pubkeys` — the per-block `next_pubkey` chain.
  - **Public-key advertisement.** Issuer Ed25519 public key (TV-W-1
    persona-(0, 0) sub-key) plus the three `next_pubkey` chain links.
- The top-level `pin_pack_sha256` field is SHA-256 of the
  JCS-canonical form of the pin-pack body (chain projection +
  traces + metadata, without the hash slot itself).

## Cross-vector anchors

The issuer Ed25519 public key is the persona-(0, 0) sub-key of the
TV-W-1 pin-pack. A drift in the BIP-32 / SLIP-0010 derivation surface
trips the TV-W-1 cross-compat anchor first
(`test_cross_compat_pubkeys_align_with_capability_token_pin`); the
TV-W-2 fixture is the dependent consumer.

## Determinism notes

- **Ed25519 (RFC 8032)** signatures are deterministic; all four
  signers in this chain (issuer + three `next_pubkey` slots) produce
  byte-stable signatures across runs.
- The chain `next_pubkey` slots are derived deterministically from
  the TV-W-1 seed via a labelled SHA-256 expansion
  (see `_derive_chain_seed` in
  `wirelang/tests/_tv_w_2_pin_pack_builder.py`). This avoids needing
  a full BIP-32 sub-tree for the chain while keeping the chain
  fully reproducible.
- **§4-CSC.** Each block's caveat-set is hashed via
  `wirelang.canonical.caveat_set.canonical_caveat_set_hash`, which
  applies (1) whitespace normalisation, (2) dedup, (3) lexicographic
  sort, (4) JCS-array serialisation, and SHA-256 of the resulting
  bytes. Producer caveat order in the builder is deliberately *not*
  lex-sorted so the CSC sort step is exercised.

## Regeneration

```
python -m wirelang.tests._tv_w_2_pin_pack_builder
```

To compute the pin-pack hash without writing the fixture:

```
python -m wirelang.tests._tv_w_2_pin_pack_builder --check
```

A re-baseline is an explicit engineering event; per
`datalog-caveat-vocabulary-phase-2.md` §6.3 it is triggered by
vocabulary additions, §4-CSC clarifications, schema bumps, or
upstream Biscuit-rs/py block-payload-layout patches.

## Brand-Guide §9 compliance

All identifiers are role-strings:

- Issuer: `tv-w-2-issuer-0-0`.
- Audience patterns: `role=consumer-A` / `role=consumer-B` /
  `role=consumer-A,scope=read-only` /
  `role=consumer-A,scope=read-only,rate=capped`.

No clear personal names appear in the fixture, the builder, or the
test module.
