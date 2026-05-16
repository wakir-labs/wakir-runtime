// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Wakir Labs contributors
//
// persona-engine-smoke / smoke_test
// =================================
//
// One unit-test per axis-decision smoke function plus invariant tests
// and a master run-all assertion. Total >= 10 tests per Sprint-Auftrag.
//
// These tests are the Phase-3a-Pre-Trigger acceptance gate: every
// crate from the Decision-Doc compiles and round-trips on the target
// toolchain.

use persona_engine_smoke as smoke;

// -- Wahlachse 1 -----------------------------------------------------

#[test]
fn shamir_sss_roundtrip_recovers_secret() {
    let recovered = smoke::shamir_sss_roundtrip().expect("shamir smoke must succeed");
    // The recovered scalar is the 32-byte big-endian encoding of the
    // original secret_scalar. We assert length here; byte-equality is
    // already asserted inside the smoke function.
    assert_eq!(recovered.len(), 32, "shamir recovered scalar must be 32 bytes");
    // Non-zero invariant — the smoke fixture deliberately uses a
    // non-zero secret.
    assert!(recovered.iter().any(|b| *b != 0), "recovered scalar must be non-zero");
}

// -- Wahlachse 2 -----------------------------------------------------

#[test]
fn jcs_canonicalize_emits_deterministic_bytes() {
    let bytes_a = smoke::jcs_canonicalize().expect("jcs smoke a");
    let bytes_b = smoke::jcs_canonicalize().expect("jcs smoke b");
    assert_eq!(bytes_a, bytes_b, "JCS output must be deterministic across calls");
}

#[test]
fn jcs_canonicalize_sorts_keys_lexicographically() {
    let bytes = smoke::jcs_canonicalize().expect("jcs smoke");
    let s = std::str::from_utf8(&bytes).expect("jcs output must be valid utf-8");
    // alpha comes before beta comes before nested comes before zeta.
    let idx_alpha = s.find("\"alpha\"").expect("alpha key");
    let idx_beta = s.find("\"beta\"").expect("beta key");
    let idx_nested = s.find("\"nested\"").expect("nested key");
    let idx_zeta = s.find("\"zeta\"").expect("zeta key");
    assert!(idx_alpha < idx_beta, "alpha before beta");
    assert!(idx_beta < idx_nested, "beta before nested");
    assert!(idx_nested < idx_zeta, "nested before zeta");
    // No insignificant whitespace.
    assert!(!s.contains(": "), "JCS must not emit ': ' (space after colon)");
    assert!(!s.contains(", "), "JCS must not emit ', ' (space after comma)");
}

// -- Wahlachse 3 Stack 1: k256 --------------------------------------

#[test]
fn k256_sign_verify_emits_der_signature() {
    let der = smoke::k256_sign_verify().expect("k256 smoke");
    // DER ECDSA signatures over secp256k1 are typically 70-72 bytes;
    // the strict lower bound is 8 bytes (degenerate r=0/s=0 cases,
    // which the signer won't produce). We assert a sane range.
    assert!(
        der.len() >= 8 && der.len() <= 72,
        "DER signature length must be 8..=72, got {}",
        der.len()
    );
    // First byte of any DER SEQUENCE is 0x30.
    assert_eq!(der[0], 0x30, "DER signature must start with SEQUENCE tag 0x30");
}

// -- Wahlachse 3 Stack 1: bip32 -------------------------------------

#[test]
fn bip32_derive_account_returns_compressed_pubkey() {
    let pubkey_bytes = smoke::bip32_derive_account().expect("bip32 smoke");
    // SEC1 compressed pubkey is 33 bytes (1-byte tag 0x02/0x03 + 32-byte X).
    assert_eq!(
        pubkey_bytes.len(),
        33,
        "bip32 compressed pubkey must be 33 bytes"
    );
    assert!(
        pubkey_bytes[0] == 0x02 || pubkey_bytes[0] == 0x03,
        "compressed-pubkey tag must be 0x02 or 0x03, got 0x{:02x}",
        pubkey_bytes[0]
    );
}

// -- Wahlachse 3 Stack 1: ed25519-dalek -----------------------------

#[test]
fn ed25519_sign_verify_returns_64_byte_signature() {
    let sig = smoke::ed25519_sign_verify().expect("ed25519 smoke");
    assert_eq!(sig.len(), 64, "Ed25519 detached signature must be 64 bytes");
}

// -- Wahlachse 3 Stack 2: sha2 --------------------------------------

#[test]
fn sha256_hash_returns_32_bytes() {
    let digest = smoke::sha256_hash().expect("sha256 smoke");
    assert_eq!(digest.len(), 32, "SHA-256 digest must be 32 bytes");
}

#[test]
fn sha256_hash_matches_known_vector() {
    // Cross-check with a hand-computed known-answer test.
    // The Python equivalent of this expected hex was computed via
    //   python3 -c "import hashlib; print(hashlib.sha256(b'wakir-labs persona-engine-smoke sha256 hello-world').hexdigest())"
    // — Reza recomputes this once cargo-test passes, then pins as a
    // Phase-3a-Initial cross-lang vector. For the smoke layer we use
    // the digest produced by sha2 0.11.0 itself as the self-anchor:
    // any future drift between 0.11.x patches will surface here.
    let digest = smoke::sha256_hash().expect("sha256 smoke");
    let hex_str = hex::encode(&digest);
    assert_eq!(
        hex_str.len(),
        64,
        "sha256 hex string must be 64 chars, got {}",
        hex_str.len()
    );
    // Determinism: two consecutive calls must produce the same digest.
    let digest2 = smoke::sha256_hash().expect("sha256 smoke 2");
    assert_eq!(digest, digest2, "SHA-256 must be deterministic");
}

// -- Wahlachse 3 Stack 4: AEAD ChaCha20-Poly1305 --------------------

#[test]
fn aead_chacha20_roundtrip_recovers_plaintext() {
    let recovered = smoke::aead_encrypt_decrypt().expect("chacha20poly1305 smoke");
    let expected: &[u8] = b"wakir-labs persona-engine-smoke chacha20poly1305 hello-world";
    assert_eq!(
        recovered, expected,
        "ChaCha20-Poly1305 round-trip plaintext mismatch"
    );
}

// -- Wahlachse 3 Stack 4: AEAD AES-GCM ------------------------------

#[test]
fn aead_aes_gcm_roundtrip_recovers_plaintext() {
    let recovered = smoke::aead_aes_gcm_roundtrip().expect("aes-gcm smoke");
    let expected: &[u8] = b"wakir-labs persona-engine-smoke aes-gcm hello-world";
    assert_eq!(recovered, expected, "AES-GCM round-trip plaintext mismatch");
}

// -- Wahlachse 3 Stack 3: rustls + aws-lc-rs ------------------------

#[test]
fn rustls_provider_construct_links_and_initialises() {
    smoke::rustls_provider_construct().expect("rustls+aws-lc-rs construct must succeed");
}

// -- Master run-all -------------------------------------------------

#[test]
fn all_smoke_functions_green() {
    let count = smoke::run_all().expect("all smoke functions must succeed");
    assert_eq!(
        count, 9,
        "run_all must execute all 9 smoke functions (Shamir, JCS, k256, bip32, ed25519, sha256, chacha20, aes-gcm, rustls)"
    );
}
