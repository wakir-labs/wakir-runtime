<!-- SPDX-License-Identifier: CC-BY-4.0 -->
# Wirelang Layer 3 — Capability Token (Biscuit v3 + AIP)

Layer 3 carries the *trust* concern of Wirelang: who is allowed to do
what, on whose behalf, until when. The on-the-wire token is a Biscuit v3
binary; this module describes the JSON projection used inside Wirelang
frames and registries, plus the AIP document that anchors the issuer's
root key.

## 1. Substrate adoption

| Concern | Substrate | Reference |
|---|---|---|
| Token format | Biscuit v3 (default v3.3) | eclipse-biscuit/biscuit `SPECIFICATIONS.md`, sections *Format*, *Blocks*, *Signature (one block)*, *Signature (appending)*, *Signature (sealing)*, *Ed25519* |
| Identity document | AIP `draft-prakash-aip-00` | IETF datatracker `draft-prakash-aip-00`, section 2.3 (document fields), section 2.2 (identifier schemes), section 3.2 (chained mode) |
| Signature algorithm | Ed25519 (RFC 8032) | Biscuit `SPECIFICATIONS.md` *Algorithms / Ed25519* |
| Canonical JSON | RFC 8785 (JCS) | inherited from Layer 1 |

Verified URL-200 stamps (P7 discipline, 2026-05-06):

- `https://github.com/eclipse-biscuit/biscuit/blob/main/SPECIFICATIONS.md`
  — accessible 2026-05-06, document confirms format integers v3.0=3 …
  v3.3=6.
- `https://datatracker.ietf.org/doc/html/draft-prakash-aip-00` —
  accessible 2026-05-06, status: Active Internet-Draft, expires
  2026-09-28.

## 2. Token shape

A Layer-3 capability token in JSON projection (see
`wirelang/schemas/layer-3-capability-token.json`):

```
{
  "version": "biscuit-v3",
  "biscuit_format_version": 6,
  "aip_document_ref": "<URI of issuer's AIP document>",
  "authority_block": {
    "issuer_did": "aip:web:wakir.dev/<issuer-role>",
    "audience_pattern": "role=<consumer-role>",
    "caveats": [ "<datalog statement>", ... ],
    "not_before": "<RFC 3339>",
    "not_after":  "<RFC 3339>",
    "nonce":      "<hex, >= 16 bytes>",
    "signature":  "<Ed25519, 64 bytes hex>",
    "next_pubkey":"<Ed25519, 32 bytes hex>"
  },
  "append_blocks": [ { "audience_pattern": ..., "caveats": ..., "signature": ..., "next_pubkey": ... }, ... ],
  "proof_block": { "final_signature": "...", "sealed_at": "..." }   // optional, sealing
}
```

### 2.1 Authority block

The authority block is Block 0 in Biscuit terms. Wakir-side fields are
a structured projection of Datalog facts and checks; the canonical
binary remains the on-the-wire artefact.

- `issuer_did` accepts AIP identifiers (`aip:web:` and `aip:key:ed25519:`)
  per AIP draft section 2.2, plus `did:web:` for cross-compat with the
  Layer-1 `source` field.
- `caveats` is an array of Datalog statements. See section 4 for the
  initial Wakir caveat vocabulary.
- `signature` is Ed25519 over the canonical authority-block payload,
  verified against the public key referenced by `aip_document_ref`
  (preferring `biscuit_root_pubkey` extension, falling back to a
  `public_keys` entry with `purpose: "biscuit-root"`).
- `next_pubkey` (`pk_1`) signs the next block. Its absence is a fatal
  validation error.

### 2.2 Append blocks

Append blocks attenuate. Per Biscuit *Signature (appending)*: each block
adds further checks but cannot expand authority. Each append block has
its own `audience_pattern`, `caveats`, `signature` (over its data and
the previous `next_pubkey`), and a fresh `next_pubkey` for further
attenuation. `external_signature` carries the v1 third-party block
signature when an external party co-signs.

### 2.3 Proof block (sealing)

When present, the token is sealed and MUST NOT be further attenuated.
`final_signature` covers the last block's data, the algorithm marker,
the public key, and the previous signature, per Biscuit *Signature
(sealing)*. `sealed_at` is informational and not part of Biscuit core.

## 3. AIP document anchoring

The issuer's AIP document (see `wirelang/schemas/aip-document.json`)
provides the root verification material. Conforms to
`draft-prakash-aip-00` section 2.3 with the required fields `aip`, `id`,
`public_keys`, `name`, `delegation`, `protocols`, `document_signature`,
`expires`. Wakir extensions are strictly additive and ignored by a
strict AIP parser:

- `verification_methods` — DID-document-style verification methods,
  useful for cross-org federation.
- `service_endpoints` — DID-document-style service endpoints.
- `biscuit_root_pubkey` — convenience pointer to the Ed25519 key used
  as Biscuit root for tokens that reference this AIP document.

Resolution flow:

1. Verifier reads `token.aip_document_ref`, fetches the AIP document
   (well-known path under `aip:web:` host, or pinned URL).
2. Verify `document_signature` over JCS-canonicalised document body
   using `public_keys[document_signature.kid]`.
3. Resolve Biscuit root key in this order: `biscuit_root_pubkey` →
   `public_keys` entry with `purpose=biscuit-root` → reject.
4. Verify Biscuit authority block signature against the resolved key.
5. Verify the chain of append blocks per Biscuit `Verifying`.
6. If `proof_block` is present, run sealed verification.

## 4. Datalog caveat vocabulary (Phase 1a draft)

The Wakir Phase-1a caveat vocabulary is a small initial set sufficient
for treasury and inter-agent capability flows. Full vocabulary
specification — including formal grammar and semantic-validity tests —
is **deferred to Phase-1a-Tag-3+**. This section is the working draft.

| Predicate | Arity | Meaning |
|---|---|---|
| `action(<str>)` | 1 | Allowed action name (e.g. `"read.balance"`, `"submit.tx"`). |
| `env(<str>)` | 1 | Allowed environment (`"dev"`, `"staging"`, `"prod"`). |
| `time($t)` | 1 | Time variable bound by the verifier; combine with `<` / `>` for windows. |
| `audience(<str>)` | 1 | Audience role or AIP id. |
| `rate_limit($n)` | 1 | Per-window invocation limit. |
| `read_only(<bool>)` | 1 | Restrict to read-only operations. |
| `attests($hash)` | 1 | Require a TEE attestation hash (Phase-1b). |
| `wat_anchor($id)` | 1 | Cross-reference WAT anchor id (Phase-1b). |

Layer-3 schema accepts any string in `caveats`; semantic validation
against this vocabulary lives in the verifier and is enforced by Biscuit
Datalog evaluation, not by the JSON Schema.

## 5. Security assumptions

- **Ed25519 signing** per RFC 8032. Nonce-misuse-resistant by
  construction; signers MUST still source `nonce` from a CSPRNG.
- **JCS canonicalisation** for AIP-document signatures. Any
  serialisation deviation invalidates `document_signature`.
- **Replay protection** via per-token `nonce` in the authority block.
  Verifiers SHOULD maintain a bounded nonce-cache for the token's
  validity window.
- **Audience binding** is mandatory. A token without `audience_pattern`
  is rejected by the schema; the verifier additionally enforces
  audience match against the request context.
- **Validity window invariant** `not_before < not_after` is verifier-
  enforced (not expressible in pure JSON Schema 2020-12).
- **Sealing is irrevocable.** Once `proof_block` is set, the token
  cannot be further attenuated; the verifier rejects any further
  append-block additions even if the binary still permits them.
- **Two-curve stack** (Phase 1a): Ed25519 for AIP / Biscuit signatures,
  secp256k1 for BIP32 derivation root and treasury-side anchoring.
  Document layout in `aip-document.json` accepts both algorithms in
  `public_keys[*].alg`.

## 6. Out of scope (Tag 2)

- Identity-substrate implementation: BIP32 master setup, Ed25519
  derivation paths, key-rotation flow. Deferred to Phase-1a-Tag-3+.
- Verifier reference implementation. Deferred to Phase-1b.
- Full Datalog caveat grammar with formal-semantics tests. Phase-1a-Tag-3+.
- WAT × Layer-3 cross-anchoring of capability-burst hashes. Cross-review
  zone 2 with the WAT module owner.

## 7. Brand-Guide §9 compliance

All examples use role strings (`treasury-issuer`, `treasury-agent`,
`cfo-agent`). No personal clear names appear in schemas, examples, tests,
or this spec text.

— *role: wirelang-spec-owner*
