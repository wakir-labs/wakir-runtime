# Proof-Path Test Vectors

Shared Merkle test vectors for the WAT proof path. The same three files
are meant to be loaded by all three repositories:

- `wakir-runtime` — `wat.merkle.aggregator` (tree builder, proof emitter)
- `wakir-verify` — `wakir_verify.merkle_proof` (independent verifier)
- `wakir-protocol` — `tests/test_proof_path_vectors.py` (reference
  re-computation from first principles: `hashlib` + RFC 8785 JCS)

They exist so that the three implementations cannot drift apart without
a test going red (ADR-0072 Phase 4, sub-item 4c). The vectors are
re-derived from first principles by the protocol smoke test and driven
through both counterpart implementations by the `compat` gate
(`tooling/compat/run_vectors_with.py`, see `docs/cross-repo-compat.md`).

## Hash rules (derived from the shipped Merkle code)

| Rule | Definition |
|---|---|
| Hash function | SHA-256 (FIPS 180-4), raw 32-byte digests internally, lower-case hex on the wire |
| Leaf hash | `sha256(JCS(leaf))` where `leaf = {event_id, time, payload_hash, capability_token_hash}` serialised per RFC 8785. All four keys are always present; `capability_token_hash` may be the empty string. |
| Inner node | `sha256(left || right)` over the two raw 32-byte child digests |
| Odd level | Duplicate the last node before pairing (Bitcoin convention). The recorded `levels[n]` show the post-duplication layout. |
| Single leaf | Root equals the leaf hash; the sibling path is empty |
| Sibling side | `L`: `sha256(sibling || current)`; `R`: `sha256(current || sibling)`. Sibling paths are listed bottom-up. |

## Files

| File | Scenario | Invariant exercised |
|---|---|---|
| `vector-1.json` | 1 leaf | root == leaf hash, empty sibling path |
| `vector-2.json` | 3 leaves (odd) | duplicate-last: the proof for index 2 carries its own hash as the level-0 sibling on side `R` |
| `vector-3.json` | 3 leaves + tampered leaf 1 | `tampered.proof` (built from the honest tree) must yield `verified == false` for `tampered.leaf_hash` |

## Vector layout

```text
schema        "wakir-proof-path-vector/v1"
vector_id     file stem
hash_rules    the table above, machine-readable
leaves[]      the four-field leaf tuples, in tree order
leaf_hashes[] hex leaf hashes (same order)
levels[][]    every tree level post-duplication, bottom-up; levels[-1] == [merkle_root]
merkle_root   hex
manifest      a wakir-wat-manifest/v1 instance for the same tree, shaped
              like the runtime aggregator output (version, hour_slot,
              merkle_root, event_count, events == leaves rows with
              leaf_hash, tree_levels, build_time, prev_hour_root: null);
              validates against wakir-wat-manifest-v1.json and loads
              with wakir_verify.manifest.load_manifest_from_dict
proofs[]      one wakir-inclusion-proof/v1 document per leaf
expected[]    {leaf_index, verified} — all true
tampered      (vector-3 only) {leaf, leaf_hash, proof, expected_verified: false}
```

Each `proofs[]` entry validates against the canonical
`wakir_protocol/schemas/wakir-inclusion-proof-v1.json`
(`additionalProperties: false`; `manifest_version` is the manifest's
`version`, `hour` its `hour_slot`). The schema's `examples` are
`vector-1.proofs[0]` and `vector-2.proofs[2]`.

Leaf rows use 64-hex `capability_token_hash` values only: the Merkle
leaf rule permits the empty string, but `wakir-wat-manifest-v1.json`
requires a 64-hex digest per manifest event row, and the same leaves
serve as both. The empty-string leaf case stays covered by
`tests/fixtures/jcs-leaf-vectors/vector-3-no-capability-token.json`.

## Regenerating

The vectors are deterministic. The reference recomputation lives in
`tests/test_proof_path_vectors.py` and in
`tooling/compat/run_vectors_with.py --impl reference`; to check a
counterpart checkout against them:

```text
python3 tooling/compat/run_vectors_with.py --impl runtime <wakir-runtime checkout>
python3 tooling/compat/run_vectors_with.py --impl verify  <wakir-verify checkout>
```

Do not regenerate to "fix" a red test — a mismatch means one of the
three implementations changed its hash rules.
