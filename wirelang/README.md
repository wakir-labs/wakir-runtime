<!-- SPDX-License-Identifier: Apache-2.0 -->
# Wirelang

Wirelang is the typed inter-agent messaging layer of the Wakir Runtime.
Agents inside an organisation, and across organisations through federation,
exchange messages as **Wirelang frames** that are wire-stable, hash-stable,
and schema-versioned.

## Layer architecture

Wirelang is a four-layer stack. This module currently ships Layers 0–2.

| Layer | Concern | Substrate |
|---|---|---|
| **0 — Transport** | Subject routing, durable streams, delivery semantics | NATS + JetStream |
| **1 — Wire format** | Envelope, mandatory and extension attributes, hash stability | CloudEvents 1.0 + Wakir extensions, JSON canonical (RFC 8785) |
| **2 — Semantic** | Schema-registry references, vocabulary anchors, validity windows | JSON Schema 2020-12 |
| **3 — Trust** | Capability tokens, attenuation, identity-document anchoring | AIP `draft-prakash-aip-00` + Biscuit v3 (Ed25519) |

Layer 4 (WAT audit anchoring) sits above Layer 3 and is owned by the
WAT module.

## Layout

```
wirelang/
  schemas/      # JSON-Schema 2020-12 definitions for Layers 0, 1, 2
  specs/        # Markdown spec text and frame walkthroughs
  examples/     # Reference frames used as test fixtures
  tests/        # pytest + jsonschema schema-compliance tests
```

## Running the tests

```bash
pip install jsonschema pytest
pytest wirelang/tests
```

The test suite covers schema self-validity, the example frames and tokens,
and at least five positive and five negative cases per layer (Layers 0–2)
plus seven positive and ten negative cases each for Layer-3 capability
tokens and AIP documents.

## Design notes

- **Adoption over invention.** Layers 0 and 1 stand on NATS, CloudEvents,
  and IETF-final formats (JCS, CBOR, JSON Schema). The Wakir-specific work
  lives in Layer 2 (vocabulary, schema-registry semantics) and Layer 3.
- **Hash stability is mandatory.** Frames intended for downstream audit
  anchoring must be serialised with RFC 8785 JSON Canonicalization.
- **Pseudonymisation by default.** Agent identity travels as a `did:web`
  DID plus a role string. Personal or clear names do not appear on the wire.
- **Forward-compatible reservations.** Several optional Layer-1 fields
  (`attestationref`, `personahash`, `imagedigest`) are reserved today and
  populated by later phases without a schema break.

## License

Apache License 2.0. See `LICENSE` and `NOTICE` at the repository root.
