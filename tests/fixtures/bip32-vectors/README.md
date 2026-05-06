# BIP-32 Test-Vector Fixtures

Canonical BIP-32 test vectors used for regression testing
``wirelang.identity.key_derivation`` (secp256k1 master + CKDpriv).

## Source

- BIP-32 spec, Appendix "Test vectors":
  <https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki>
  (URL-200-stamped 2026-05-06.)

## Files

- ``vector-1.json`` — seed ``000102030405060708090a0b0c0d0e0f`` (smallest
  spec vector; pre-existing inline-tested by
  ``test_identity_key_derivation`` and now mirrored as a fixture).
- ``vector-2.json`` — seed ``fffcf9f6f3f0edeae7e4...4b484542`` (large
  random seed, exercises mixed hardened/non-hardened derivation up to
  depth 5).
- ``vector-3.json`` — seed ``4b381541583be4...c51c73235be`` (the
  "leading-zero private key" vector that historically broke
  implementations that stripped a leading 0 byte from the key).

## Schema

Each fixture is a JSON object with this shape::

    {
      "spec":   "BIP-32",
      "source": "<URL>",
      "seed_hex": "<seed bytes, lowercase hex>",
      "chain": [
        {
          "path":       "m/0/2147483647H",
          "depth":      <int>,
          "child_num":  <int (raw 32-bit, hardened indices have bit 31 set)>,
          "xprv":       "<base58check encoded extended private key>",
          "xpub":       "<base58check encoded extended public key>",
          "priv_hex_32":"<32-byte private scalar, lowercase hex>",
          "chain_code": "<32-byte chain code, lowercase hex>",
          "pub_hex_33": "<33-byte compressed public key, lowercase hex>"
        },
        ...
      ]
    }

The ``priv_hex_32``, ``chain_code`` and ``pub_hex_33`` fields are
derived from the canonical ``xprv``/``xpub`` strings via Base58Check
decode and are pinned here so the test suite does not need a Base58
dependency at run time. Any change to these fields must also update
``xprv``/``xpub`` (or vice-versa); the test
``test_bip32_full_vectors.test_fixtures_internally_consistent``
catches drift.

## Brand-Guide §9 note

Fixtures contain no clear personal names; only spec-derived hex bytes
and standard BIP-32 path strings.
