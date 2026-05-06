# SLIP-0010 Ed25519 Test-Vector Fixtures

Canonical SLIP-0010 test vectors for Ed25519 key derivation, used by
``test_slip0010_ed25519_full_vectors.py`` to regression-test
``wirelang.identity.key_derivation`` (Ed25519 master + CKDpriv).

## Source

- SLIP-0010 spec, "Test vectors for ed25519":
  <https://github.com/satoshilabs/slips/blob/master/slip-0010.md>
  (URL-200-stamped 2026-05-06.)

## Files

- ``vector-1.json`` — seed ``000102030405060708090a0b0c0d0e0f``
  (smallest spec vector; mirrors BIP-32 TV1 seed but produces different
  master keys because the HMAC key differs ("Bitcoin seed" vs
  "ed25519 seed")).
- ``vector-2.json`` — large random seed
  ``fffcf9f6f3f0edeae7e4...4b484542``, depth-5 hardened-only chain.

## Schema

::

    {
      "spec": "SLIP-0010 (ed25519)",
      "source": "<URL>",
      "seed_hex": "<seed bytes, lowercase hex>",
      "chain": [
        {
          "path":         "m/0H/2147483647H",
          "child_indices": [<int (raw 32-bit, hardened bit set)>, ...],
          "chain_code":   "<32-byte chain code, lowercase hex>",
          "priv_hex_32":  "<32-byte private seed, lowercase hex>",
          "pub_hex_33":   "<33-byte SLIP-0010 ed25519 public form: 0x00 || 32-byte raw pubkey>",
          "pub_hex_32":   "<32-byte raw ed25519 public key (pub_hex_33 minus the 0x00 prefix)>"
        },
        ...
      ]
    }

The SLIP-0010 spec writes the public key as 33 bytes with a leading
``0x00`` so the size matches secp256k1 compressed-point form. Our
production helper :func:`wirelang.identity.ed25519_public_from_private`
returns the 32-byte raw form (RFC 8032), so the fixture stores both
``pub_hex_33`` (spec-form, exact match for the table in the SLIP-0010
text) and ``pub_hex_32`` (what our library produces).

Hardened-only: SLIP-0010 ed25519 supports no non-hardened derivation,
so every ``child_indices`` entry has bit 31 set
(``index >= 0x8000_0000``).

## Brand-Guide §9 note

Fixtures contain no clear personal names; only spec-derived hex bytes
and standard SLIP-0010 path strings.
