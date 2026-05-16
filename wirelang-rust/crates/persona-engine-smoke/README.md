<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Wakir Labs contributors
-->

# persona-engine-smoke

Hello-World smoke-tests for the ten Phase-3a Rust crate choices.

## Purpose

Substantive pre-confirmation that the crates chosen in
[`docs/decisions/rust-rewrite-crate-wahlen.md`](../../../docs/decisions/rust-rewrite-crate-wahlen.md)
actually compile and round-trip on the target toolchain (rustc 1.85
stable channel) before the Phase-3a-Trigger (~KW 27, ~2026-06-26).

This crate is **not** a production primitive layer. It exists only so
that crate-version drift, link-time conflicts, or feature-flag misses
surface here — early — and not in the Phase-3a-Initial-Sprint hot
window.

## Scope

One smoke function per Decision-Doc axis:

| Wahlachse | Function | Crate(s) |
|---|---|---|
| 1 — Shamir-Secret-Sharing | `shamir_sss_roundtrip` | `vsss-rs =5.4.0` |
| 2 — JSON-Canonicalization | `jcs_canonicalize` | `serde_jcs =0.2.0` |
| 3 Stack 1 — secp256k1 ECDSA | `k256_sign_verify` | `k256 =0.13.4` |
| 3 Stack 1 — BIP32 derivation | `bip32_derive_account` | `bip32 =0.5.3` + `k256` |
| 3 Stack 1 — Ed25519 sig/verify | `ed25519_sign_verify` | `ed25519-dalek =2.2.0` |
| 3 Stack 2 — SHA-256 | `sha256_hash` | `sha2 =0.11.0` |
| 3 Stack 3 — TLS / SVID construct | `rustls_provider_construct` | `rustls =0.23.40` + `aws-lc-rs =1.17.0` |
| 3 Stack 4 — AEAD ChaCha20-Poly1305 | `aead_encrypt_decrypt` | `chacha20poly1305 =0.10.1` |
| 3 Stack 4 — AEAD AES-GCM | `aead_aes_gcm_roundtrip` | `aes-gcm =0.10.3` |

The TLS smoke is a **construct-only** test — it builds a rustls
`ClientConfig` wired to the aws-lc-rs `CryptoProvider` but does not
open a network socket. Live TLS-1.3 handshake against a test-SPIRE
server is Phase-3a-Initial-Sprint scope per Decision-Doc.

## Running

```
cd wirelang-rust
cargo test -p persona-engine-smoke
```

All tests must pass (`cargo test` green) for the crate-wahl
pre-confirmation to be valid.

## Cross-references

- ADR-0063 §Folgeartefakte Item 1 — Reza-Crate-Wahl-Klärung-Folge.
- `docs/decisions/rust-rewrite-crate-wahlen.md` — full per-axis
  rationale, HTTP-200 stamps, and risk assessments.
- `docs/decisions/persona-engine-rust-rewrite-roadmap.md` §2.3 —
  the three open Crate-Wahl questions this work answers.

## Non-goals

- No cross-language byte-equivalence (Python ↔ Rust). That is the
  Phase-3a-Initial-Sprint test-vector-suite scope.
- No production-primitive surface. Reach for the sister `persona-*`
  crates for production hashing, JCS, persona-engine logic.
- No `cargo audit` gate (Phase-3a-Trigger-Pre-Check item).

— Reza Tehrani (Dev-Engineering-2), 2026-05-16
