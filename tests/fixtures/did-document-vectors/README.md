# DID-Document Golden Vectors

Frozen reference did:web DID documents with the Wakir two-curve-stack
verification methods, used by ``test_did_document_golden.py`` to
detect unintended drift in:

- :func:`wirelang.identity.generate_persona_did_document` field layout
- :func:`wirelang.identity.sign_did_document` JCS-canonicalisation
- :func:`wirelang.identity.verify_did_signature` ECDSA-secp256k1
  verification
- :func:`wirelang.identity.did_document.did_document_publication_path`
  versioned-path convention (consensus marker B2)

## Source

- W3C DID-Core (URL-200-stamped 2026-05-06):
  <https://www.w3.org/TR/did-core/>
- did:web method (URL-200-stamped 2026-05-06):
  <https://w3c-ccg.github.io/did-method-web/>
- EcdsaSecp256k1Signature2019 (URL-200-stamped 2026-05-06):
  <https://w3c-ccg.github.io/lds-ecdsa-secp256k1-2019/>
- Ed25519VerificationKey2020 (URL-200-stamped 2026-05-06):
  <https://w3c-ccg.github.io/security-vocab/>
- RFC 8785 JCS (URL-200-stamped 2026-05-06):
  <https://datatracker.ietf.org/doc/html/rfc8785>

Note on signature determinism: ECDSA-secp256k1 signatures produced by
``cryptography.hazmat`` are *not* deterministic in the RFC 6979 sense;
``r`` and ``s`` vary across runs even for identical inputs. Therefore
the fixture's ``proof_block.signatureHex`` is captured only as a
"this signature, produced at fixture-generation time, must verify"
anchor, not as a byte-equality target. The test verifies the
signature with the public key but does not require regeneration to
produce the same bytes. The ``document_jcs_sha256`` field, by
contrast, *is* byte-stable (SHA-256 of JCS bytes) and serves as the
drift-detector for the document layout.

## Files

- ``vector-1-default.json`` — default host (``wakir.dev``), version=1.
- ``vector-2-versioned.json`` — version=3, demonstrates versioned-path
  convention.
- ``vector-3-staging-host.json`` — non-default host
  (``staging.wakir.dev``), version=2.

## Schema

::

    {
      "label":            "...",
      "spec":             "W3C DID-Core (did:web) + Wakir two-curve extension",
      "url_200_stamped":  "2026-05-06",
      "generation_inputs": {
        "persona_id":           "...",
        "host":                 "wakir.dev",
        "version":              <int >= 1>,
        "secp256k1_pub_hex_33": "<33-byte compressed point, hex>",
        "secp256k1_priv_hex_32":"<32-byte private scalar, hex (test-only)>",
        "ed25519_pub_hex_32":   "<32-byte raw, hex>"
      },
      "document":              { /* DID document body, including 'proof' */ },
      "document_jcs_sha256":   "<64-hex SHA-256 of JCS(body without proof)>",
      "proof_block":           { "type": "EcdsaSecp256k1Signature2019", ... }
    }

## Brand-Guide §9 note

All ``persona_id`` values are role-strings; no clear personal names.
Signing keys are test fixtures derived from canonical spec seeds.
