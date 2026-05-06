<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Creative Commons Attribution 4.0 International
License. Full text: https://creativecommons.org/licenses/by/4.0/
-->

# WAT Hash — Cross-Domain Specification

Version: `wakir-wat-hash/v1`
Status: stable for Phase 1a.
Audience: any module that produces or consumes WAT-anchored data —
Wirelang bridges, the WAT aggregator, future zk-proof companions,
external auditors.

This document fixes the cross-domain hash contract that Wirelang and
WAT both depend on. It is intentionally separate from the WAT
manifest specification (`docs/wat-manifest-spec.md`) because the
contract applies to multiple call sites — leaf hashing, payload
hashing, future schema-anchor hashing — and at least two modules
under different licences (Wirelang Apache-2.0 and WAT BSL-1.1).

## 1. Three steps, one rule

```
hash = hex_lower( SHA-256( JCS( object ) ) )
```

| step             | spec                          | parameters                                |
| ---------------- | ----------------------------- | ----------------------------------------- |
| canonicalisation | RFC 8785 (JCS)                | UTF-8 output, sorted keys, no whitespace  |
| digest           | FIPS 180-4 / RFC 6234         | SHA-256, 32-byte output                   |
| encoding         | hexadecimal, lowercase        | no `0x` prefix, no separator, 64 chars    |

This is the only WAT-domain hash convention in Phase 1a. Everything
that hashes a structured value for the audit trail uses this rule:

- the WAT leaf hash (`compute_leaf_hash` over the four-field B1 tuple);
- the payload hash that the leaf consumes (`SHA-256(JCS(frame.data))`);
- future schema-registry anchor hashes (Phase 1b);
- future capability-token-burst commitments inside Wirelang frames
  (Phase 1b).

The internal Merkle-tree node hashing (`SHA-256(left || right)` over
two 32-byte siblings) is a distinct contract documented in
`wat/merkle/aggregator.py`; it does not pass through JCS because the
inputs are already 32-byte digests and the output is already binary.

## 2. JCS — RFC 8785

The JSON Canonicalization Scheme (RFC 8785, March 2020) defines a
deterministic byte-output for any well-formed JSON value. Rules
relevant to WAT hashing:

- Object keys are sorted lexicographically by their UTF-16 code-unit
  representation. For the ASCII keys WAT uses (`event_id`, `time`,
  `payload_hash`, `capability_token_hash`), this collapses to plain
  ASCII sort order.
- Whitespace between tokens is removed.
- String values are escaped per RFC 8259 with the ECMA-404 minimum-
  escape set; multi-byte UTF-8 characters are emitted as-is.
- Numbers are serialised by ECMAScript 6 `Number.prototype.toString`
  semantics (so `1.0` becomes `1`, `1e2` becomes `100`).

WAT object inputs in Phase 1a are string-only (the four B1 fields are
all strings, by construction of the leaf-projection rule). Number
serialisation therefore does not affect the leaf hash. It does affect
the payload hash when `frame.data` contains numbers, which is
expected — that is exactly why the producer canonicaliser MUST be
RFC 8785-conformant rather than the looser
`json.dumps(sort_keys=True)` shortcut.

## 3. Reference canonicaliser

The reference module is **`rfc8785`** (PyPI, Apache-2.0, Trail of
Bits). It is the only canonicaliser blessed for Phase 1a:

- license-compatible with both Wirelang (Apache-2.0) and WAT (BSL-1.1);
- maintained, audited, and tested against the RFC 8785 vectors;
- pure-Python, no native build step.

A minimal in-tree fallback (`wat/merkle/aggregator.py::_canonicalise`)
emits `json.dumps(..., sort_keys=True, separators=(',',':'))` and is
sufficient *only* for the string-only WAT-leaf inputs. Producers
handling arbitrary `frame.data` MUST use `rfc8785`; the fallback is
documented for environments where pip is locked down (e.g. air-gapped
audit verification) but is not the conformant default.

## 4. Test-vector pack

Path: `tests/fixtures/jcs-leaf-vectors/`.

Five vectors, one JSON file each. Every vector contains:

```json
{
  "input": {
    "event_id": "...",
    "time": "...",
    "payload_hash": "...",
    "capability_token_hash": "...",
    "source": "...",
    "actorrole": "...",
    "agentid": "...",
    "schemaid": "...",
    "schemaversion": "..."
  },
  "expected_leaf_hash": "<64-char hex>",
  "notes": "..."
}
```

The `input` block carries the full 9-field hour-spool tuple
(`docs/wat-spool-spec.md` §2). The four hash-input fields are passed
to `compute_leaf_hash`; the audit-metadata fields are present so the
vector files double as spool-line samples for downstream tests.

`expected_leaf_hash` is pre-computed by running the four-field input
through the reference `compute_leaf_hash` implementation in
`wat/merkle/aggregator.py`. The pre-computation is verified at the
moment the vector file is committed; any change to the reference
canonicaliser or the `compute_leaf_hash` body that breaks a vector
will fail CI before reaching main.

## 5. Drift detection

The same vector pack is consumed from two test trees:

- `tests/wat/` (WAT module tests, BSL-1.1 module).
- `wirelang/tests/` (Wirelang module tests, Apache-2.0 module).

Both trees load the JSON files at test-collection time, recompute the
leaf hash through their own code path, and assert against the
recorded `expected_leaf_hash`. A drift between the two modules — for
example, if Wirelang adopts a different canonicaliser version, or
WAT changes the leaf-tuple key order — is caught the next time CI
runs. This is cheaper than a dedicated cross-module integration
test and keeps the contract co-located with the consumers.

## 6. Forward compatibility

`wakir-wat-hash/v2` is reserved for two anticipated needs:

- **zk-proof hash extension.** A future companion module may produce
  a zero-knowledge inclusion proof for a leaf set; that proof's
  public commitment will be a digest of the same B1 tuple under a
  zk-friendly hash (e.g. Poseidon or a SNARK-friendly SHA-256
  variant). v2 will document the parallel commitment so a verifier
  can cross-check the zk-proof against the WAT leaf hash without
  re-running the canonicaliser.
- **multi-hash agility.** If SHA-256 has to be deprecated in the
  Wakir-anchored timeframe, v2 will introduce a multihash prefix
  (per the IPFS multihash spec) so old hashes remain recognisable
  while new hashes can carry a different digest.

Both extensions are additive. v1 hashes anchored under the rules
above remain valid forever.

## 7. Reference implementation

- Hash core: `wat.merkle.aggregator.compute_leaf_hash` (BSL-1.1).
- JCS canonicaliser: `rfc8785` PyPI (Apache-2.0).
- Test vectors: `tests/fixtures/jcs-leaf-vectors/` (Apache-2.0).
- Cross-module drift detector: `tests/wat/test_jcs_drift.py` and
  `wirelang/tests/test_jcs_drift.py` (Phase-1a-Tag-7 implementation).
