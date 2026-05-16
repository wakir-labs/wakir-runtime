// SPDX-License-Identifier: Apache-2.0
// Copyright (c) 2026 Wakir Labs contributors
//
// persona-engine-smoke
// ====================
//
// Hello-World smoke-test surface for the ten Phase-3a crate choices.
//
// Each public function is the minimal round-trip use-case for one
// axis-decision from `docs/decisions/rust-rewrite-crate-wahlen.md`.
// The tests in `tests/smoke_test.rs` exercise these functions and
// assert the round-trip invariants.
//
// Cross-references
// ----------------
// - ADR-0063 §Folgeartefakte Item 1
// - Decision-Doc: rust-rewrite-crate-wahlen.md (Reza, 2026-05-16)
//
// Non-goals
// ---------
// - Not a production primitive layer. The production layer lives in
//   the sister persona-* crates and follows separate spec anchors.
// - No cross-language byte-equivalence here (that is Phase-3a-Initial-
//   Sprint scope per Decision-Doc §"Smoke-Test-Empfehlung").

use std::error::Error;

/// Common result type for smoke-test functions.
pub type SmokeResult<T> = Result<T, Box<dyn Error>>;

// ---------------------------------------------------------------------
// Wahlachse 1 — Shamir-Secret-Sharing (vsss-rs 5.4.0)
// ---------------------------------------------------------------------

/// Round-trip a classical Shamir secret-sharing: split a 32-byte secret
/// into 5 shares with threshold 3, reconstruct from the first 3 shares,
/// and assert byte-equality.
///
/// This exercises only the classical Shamir surface (no Pedersen,
/// no Feldman, no VSSS) per Decision-Doc §Wahlachse 1 subset-restriction.
pub fn shamir_sss_roundtrip() -> SmokeResult<Vec<u8>> {
    use k256::Scalar;
    use rand::rngs::OsRng;
    use vsss_rs::{shamir, DefaultShare, IdentifierPrimeField, ReadableShareSet};

    // Build a deterministic 32-byte secret in the scalar field of k256
    // (vsss-rs needs a PrimeField type for classical Shamir).
    // We use the scalar group of secp256k1 here only as a convenient
    // PrimeField source; the SSS algorithm itself is field-agnostic.
    let secret_bytes: [u8; 32] = [
        0x42, 0x42, 0x42, 0x42, 0x42, 0x42, 0x42, 0x42,
        0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77,
        0x88, 0x99, 0xaa, 0xbb, 0xcc, 0xdd, 0xee, 0xff,
        0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
    ];
    let secret = k256::SecretKey::from_slice(&secret_bytes)?;
    let secret_scalar = IdentifierPrimeField(*secret.to_nonzero_scalar().as_ref());

    let threshold = 3usize;
    let limit = 5usize;
    let rng = OsRng;

    let shares: Vec<DefaultShare<IdentifierPrimeField<Scalar>, IdentifierPrimeField<Scalar>>> =
        shamir::split_secret::<DefaultShare<IdentifierPrimeField<Scalar>, IdentifierPrimeField<Scalar>>>(
            threshold,
            limit,
            &secret_scalar,
            rng,
        )
        .map_err(|e| format!("shamir split failed: {e:?}"))?;

    assert_eq!(shares.len(), limit, "share count");

    // Reconstruct from the first `threshold` shares using the
    // `ReadableShareSet::combine` trait-method (vsss-rs 5.x API).
    let subset: Vec<_> = shares[..threshold].to_vec();
    let reconstructed: IdentifierPrimeField<Scalar> = subset
        .combine()
        .map_err(|e| format!("shamir combine failed: {e:?}"))?;

    assert_eq!(
        reconstructed.0, secret_scalar.0,
        "shamir round-trip scalar mismatch"
    );

    // Return the recovered scalar's big-endian bytes for inspection.
    Ok(reconstructed.0.to_bytes().to_vec())
}

// ---------------------------------------------------------------------
// Wahlachse 2 — JSON-Canonicalization (serde_jcs 0.2.0)
// ---------------------------------------------------------------------

/// JCS-canonicalize a small object with deliberately disordered keys
/// and return the canonical UTF-8 bytes. Used as both the smoke
/// round-trip and the basis for the cross-language byte-equivalence
/// vector-suite in Phase-3a (Decision-Doc §Wahlachse 2).
///
/// The returned bytes must match `serde_jcs::to_vec` semantics:
/// keys lex-sorted, no insignificant whitespace, deterministic.
pub fn jcs_canonicalize() -> SmokeResult<Vec<u8>> {
    let value = serde_json::json!({
        "zeta": "last-key",
        "alpha": 1,
        "nested": {
            "y": [3, 2, 1],
            "x": true
        },
        "beta": null
    });
    let bytes = serde_jcs::to_vec(&value)?;
    Ok(bytes)
}

// ---------------------------------------------------------------------
// Wahlachse 3 Stack 1 — secp256k1 ECDSA (k256 0.13.4)
// ---------------------------------------------------------------------

/// secp256k1 keygen + ECDSA sign + verify round-trip over a known
/// message. Returns the DER-encoded signature for inspection.
///
/// This is the Reza Zone-L identity-substrate hauptkurve smoke-test
/// per Decision-Doc §Wahlachse 3 Stack 1.
pub fn k256_sign_verify() -> SmokeResult<Vec<u8>> {
    use k256::ecdsa::signature::{Signer, Verifier};
    use k256::ecdsa::{Signature, SigningKey, VerifyingKey};
    use rand::rngs::OsRng;

    let signing_key = SigningKey::random(&mut OsRng);
    let verifying_key: VerifyingKey = *signing_key.verifying_key();

    let message = b"wakir-labs persona-engine-smoke k256 hello-world";
    let signature: Signature = signing_key.sign(message);

    verifying_key
        .verify(message, &signature)
        .map_err(|e| format!("k256 verify failed: {e}"))?;

    Ok(signature.to_der().as_bytes().to_vec())
}

// ---------------------------------------------------------------------
// Wahlachse 3 Stack 1 — BIP32 derivation (bip32 0.5.3 + k256)
// ---------------------------------------------------------------------

/// BIP32 derive the canonical Ethereum-account path m/44'/60'/0'/0/0
/// from a deterministic seed and return the child public key's
/// SEC1-uncompressed bytes (65 bytes: 0x04 || X || Y).
///
/// This exercises the bip32 crate's `XPrv::derive_child` chain and
/// confirms the secp256k1 backend is wired through correctly
/// (Decision-Doc §Wahlachse 3 Stack 1).
pub fn bip32_derive_account() -> SmokeResult<Vec<u8>> {
    use bip32::{ChildNumber, Prefix, XPrv};

    // Deterministic 64-byte seed (NOT a production seed — smoke fixture only).
    let seed: [u8; 64] = [0x11u8; 64];

    // bip32::Error does not implement std::error::Error in 0.5.3, so
    // we wrap each fallible call via map_err to a String error type.
    let mut xprv = XPrv::new(&seed[..]).map_err(|e| format!("bip32 XPrv::new: {e:?}"))?;
    // m / 44' / 60' / 0' / 0 / 0
    let path = [
        ChildNumber::new(44, true).map_err(|e| format!("bip32 child 44': {e:?}"))?,
        ChildNumber::new(60, true).map_err(|e| format!("bip32 child 60': {e:?}"))?,
        ChildNumber::new(0, true).map_err(|e| format!("bip32 child 0': {e:?}"))?,
        ChildNumber::new(0, false).map_err(|e| format!("bip32 child 0: {e:?}"))?,
        ChildNumber::new(0, false).map_err(|e| format!("bip32 child 0 (final): {e:?}"))?,
    ];
    for c in path {
        xprv = xprv
            .derive_child(c)
            .map_err(|e| format!("bip32 derive_child {c:?}: {e:?}"))?;
    }

    let xpub = xprv.public_key();
    // Smoke-check: serialise as base58check using mainnet xpub prefix
    // and assert non-empty (exercises the bip32 crate's Base58 encoder).
    let serialised = xpub.to_string(Prefix::XPUB);
    assert!(!serialised.is_empty(), "bip32 xpub serialise empty");

    // Return the SEC1 compressed pubkey bytes (33 bytes: 0x02/0x03 || X)
    // via the k256 VerifyingKey -> EncodedPoint pathway. The inner
    // public_key() is a k256::ecdsa::VerifyingKey; converting it to
    // a compressed EncodedPoint gives the canonical 33-byte form
    // downstream consumers expect.
    let vk = xpub.public_key();
    let encoded = vk.to_encoded_point(true); // true = compressed
    Ok(encoded.as_bytes().to_vec())
}

// ---------------------------------------------------------------------
// Wahlachse 3 Stack 1 — Ed25519 sig/verify (ed25519-dalek 2.2.0)
// ---------------------------------------------------------------------

/// Ed25519 keygen + sign + verify round-trip. Returns the 64-byte
/// detached signature.
pub fn ed25519_sign_verify() -> SmokeResult<Vec<u8>> {
    use ed25519_dalek::{Signer, SigningKey, Verifier};
    use rand::rngs::OsRng;

    let mut rng = OsRng;
    let signing_key = SigningKey::generate(&mut rng);
    let verifying_key = signing_key.verifying_key();

    let message = b"wakir-labs persona-engine-smoke ed25519 hello-world";
    let signature = signing_key.sign(message);

    verifying_key
        .verify(message, &signature)
        .map_err(|e| format!("ed25519 verify failed: {e}"))?;

    Ok(signature.to_bytes().to_vec())
}

// ---------------------------------------------------------------------
// Wahlachse 3 Stack 2 — SHA-256 (sha2 0.11.0)
// ---------------------------------------------------------------------

/// Hash a known input with SHA-256 and return the 32-byte digest.
/// This is the V-907-pin / WAT-Merkle-leaf substrate smoke-test
/// (Decision-Doc §Wahlachse 3 Stack 2).
pub fn sha256_hash() -> SmokeResult<Vec<u8>> {
    use sha2::{Digest, Sha256};

    let mut hasher = Sha256::new();
    hasher.update(b"wakir-labs persona-engine-smoke sha256 hello-world");
    let digest = hasher.finalize();
    Ok(digest.to_vec())
}

// ---------------------------------------------------------------------
// Wahlachse 3 Stack 4 — AEAD ChaCha20-Poly1305 (chacha20poly1305 0.10.1)
// ---------------------------------------------------------------------

/// ChaCha20-Poly1305 AEAD encrypt + decrypt round-trip. Returns the
/// recovered plaintext, which must byte-equal the input.
///
/// This is the State-Encryption-Optional default-AEAD smoke-test
/// (Decision-Doc §Wahlachse 3 Stack 4 — ChaCha20 over AES-GCM for
/// software-CPU performance).
pub fn aead_encrypt_decrypt() -> SmokeResult<Vec<u8>> {
    use chacha20poly1305::aead::{Aead, KeyInit, OsRng as ChaChaOsRng};
    use chacha20poly1305::{ChaCha20Poly1305, Nonce};

    let key = ChaCha20Poly1305::generate_key(&mut ChaChaOsRng);
    let cipher = ChaCha20Poly1305::new(&key);

    // 96-bit nonce, fixed for this smoke-test (production code MUST
    // never reuse nonces — Decision-Doc explicitly out-of-scope here).
    let nonce_bytes = [0x07u8; 12];
    let nonce = Nonce::from_slice(&nonce_bytes);

    let plaintext: &[u8] = b"wakir-labs persona-engine-smoke chacha20poly1305 hello-world";
    let ciphertext = cipher
        .encrypt(nonce, plaintext)
        .map_err(|e| format!("aead encrypt failed: {e}"))?;
    let recovered = cipher
        .decrypt(nonce, ciphertext.as_ref())
        .map_err(|e| format!("aead decrypt failed: {e}"))?;

    assert_eq!(recovered, plaintext, "aead round-trip plaintext mismatch");
    Ok(recovered)
}

// ---------------------------------------------------------------------
// Wahlachse 3 Stack 4 — AEAD AES-GCM (aes-gcm 0.10.3) — FIPS-Pfad
// ---------------------------------------------------------------------

/// AES-256-GCM AEAD encrypt + decrypt round-trip. This is the
/// FIPS-Pfad alternative AEAD for Hosted-Service Phase-X
/// (Decision-Doc §Wahlachse 3 Stack 4).
pub fn aead_aes_gcm_roundtrip() -> SmokeResult<Vec<u8>> {
    use aes_gcm::aead::{Aead, KeyInit, OsRng as AesOsRng};
    use aes_gcm::{Aes256Gcm, Nonce};

    let key = Aes256Gcm::generate_key(&mut AesOsRng);
    let cipher = Aes256Gcm::new(&key);

    let nonce_bytes = [0x11u8; 12];
    let nonce = Nonce::from_slice(&nonce_bytes);

    let plaintext: &[u8] = b"wakir-labs persona-engine-smoke aes-gcm hello-world";
    let ciphertext = cipher
        .encrypt(nonce, plaintext)
        .map_err(|e| format!("aes-gcm encrypt failed: {e}"))?;
    let recovered = cipher
        .decrypt(nonce, ciphertext.as_ref())
        .map_err(|e| format!("aes-gcm decrypt failed: {e}"))?;

    assert_eq!(recovered, plaintext, "aes-gcm round-trip plaintext mismatch");
    Ok(recovered)
}

// ---------------------------------------------------------------------
// Wahlachse 3 Stack 3 — rustls + aws-lc-rs CryptoProvider construct
// ---------------------------------------------------------------------

/// Construct a rustls ClientConfig wired to the aws-lc-rs
/// CryptoProvider. This does NOT open a network socket — it only
/// validates that the two crates link, the provider initialises,
/// and the rustls config builder accepts it.
///
/// This is the smoke-test for Decision-Doc §Wahlachse 3 Stack 3.
/// Full TLS-1.3 handshake against a test-SPIRE-server is Phase-3a-
/// Initial-Sprint scope.
pub fn rustls_provider_construct() -> SmokeResult<()> {
    use rustls::crypto::CryptoProvider;
    use rustls::{ClientConfig, RootCertStore};
    use std::sync::Arc;

    // Initialise the aws-lc-rs provider as rustls's CryptoProvider.
    let provider: Arc<CryptoProvider> = Arc::new(rustls::crypto::aws_lc_rs::default_provider());

    // Empty root store is intentional — this smoke-test exercises the
    // builder wiring, not chain verification. The empty root store
    // means a real handshake would fail authentication, which is the
    // safe default for a smoke-only construct.
    let roots = RootCertStore::empty();

    let _config = ClientConfig::builder_with_provider(provider)
        .with_safe_default_protocol_versions()?
        .with_root_certificates(roots)
        .with_no_client_auth();

    Ok(())
}

// ---------------------------------------------------------------------
// Convenience: enumerate all smoke functions (for the master test).
// ---------------------------------------------------------------------

/// Run every smoke function in sequence and return how many succeeded.
/// Used by the `tests/smoke_test.rs::all_smoke_functions_green` master
/// test to assert the full set.
pub fn run_all() -> SmokeResult<usize> {
    let mut count = 0;
    shamir_sss_roundtrip()?;
    count += 1;
    jcs_canonicalize()?;
    count += 1;
    k256_sign_verify()?;
    count += 1;
    bip32_derive_account()?;
    count += 1;
    ed25519_sign_verify()?;
    count += 1;
    sha256_hash()?;
    count += 1;
    aead_encrypt_decrypt()?;
    count += 1;
    aead_aes_gcm_roundtrip()?;
    count += 1;
    rustls_provider_construct()?;
    count += 1;
    Ok(count)
}
