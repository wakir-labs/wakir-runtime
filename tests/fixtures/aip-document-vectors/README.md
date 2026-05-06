# AIP-Document Golden Vectors

Frozen reference AIP documents (AIP draft section 2.3 + Wakir
extensions) used by ``test_aip_document_golden.py`` to detect
unintended drift in:

- :func:`wirelang.identity.generate_aip_document` field layout
- :func:`wirelang.identity.sign_aip_document` JCS-canonicalisation
  procedure
- :func:`wirelang.identity.verify_aip_signature` Ed25519 verification
- the ``aip-document.json`` JSON Schema

## Source spec

- AIP draft (URL-200-stamped 2026-05-06):
  <https://datatracker.ietf.org/doc/html/draft-prakash-aip-00>
- RFC 8785 JCS (URL-200-stamped 2026-05-06):
  <https://datatracker.ietf.org/doc/html/rfc8785>
- RFC 8032 Ed25519 (URL-200-stamped 2026-05-06):
  <https://datatracker.ietf.org/doc/html/rfc8032>

The Ed25519 signature scheme is deterministic per RFC 8032, so a frozen
``signature_block`` is a stable byte-anchor: any future change in the
JCS bytes, in the SHA-256-of-JCS payload, or in the Ed25519
implementation will break the byte-equality test in this directory.

## Files

- ``vector-1-minimal-default.json`` — smallest valid AIP document
  (chained delegation, single Ed25519 key, default Wakir extensions
  ``verification_methods`` + ``biscuit_root_pubkey``).
- ``vector-2-wakir-extensions.json`` — both delegation, multi-protocol,
  populated ``service_endpoints`` array and ``delegation.max_depth`` /
  ``delegation.allowed_audiences``.
- ``vector-3-multi-cap-keys.json`` — three ``public_keys`` entries with
  distinct ``purpose`` values (``biscuit-root``, ``wat-anchor``,
  ``frame-signing``) covering the two-curve stack.
- ``vector-4-edge-no-extensions.json`` — strict-AIP edge case with
  *no* ``service_endpoints``, *no* ``verification_methods``, *no*
  ``biscuit_root_pubkey``: this is what an AIP-only verifier (no Wakir
  extensions) sees.

## Schema

::

    {
      "label": "<vector label>",
      "spec":  "draft-prakash-aip-00 + Wakir extensions",
      "url_200_stamped": "2026-05-06",
      "generation_inputs": {
        "persona_id": "...",
        "did_uri":    "did:web:...",
        "ed25519_pub_hex_32":  "<32-byte hex>",
        "ed25519_priv_hex_32": "<32-byte hex (test-only signing key)>",
        "valid_after": "ISO-8601 timestamp",
        "valid_until": "ISO-8601 timestamp or null",
        "expires":     "ISO-8601 timestamp",
        "delegation_mode": "chained|compact|both",
        "protocols": [...],
        "post_generation_mutations": ["human description of edits applied", ...]
      },
      "document":             { /* full AIP document body */ },
      "document_jcs_sha256":  "<64-hex SHA-256 of JCS(body without document_signature)>",
      "signature_block":      { "alg": "Ed25519", "kid": "...", "signature": "<128-hex>" }
    }

## Brand-Guide §9 note

All ``persona_id`` values are role-strings (``treasury-issuer``,
``audit-broker``, ``cfo-agent``, ``frontend-agent``); no clear
personal names anywhere in the fixtures. The signing private keys are
test fixtures derived from canonical BIP-32 / SLIP-0010 spec seeds and
have no security value.
