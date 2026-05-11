<!--
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
SPDX-License-Identifier: Apache-2.0
-->

# External-Verifier Conformance Guide — wakir-wat-manifest-v1

Status: Phase-2 Sprint-6 Tag-1 (2026-05-11).
Schema: `wirelang/schemas/wakir-wat-manifest-v1.json`, `$id` pinned to
`https://wakir.dev/wirelang/schema/wakir-wat-manifest-v1/0.2.0`.

This document is the adoption guide for third-party implementers
building a verifier for the `wakir-wat-manifest/v1` wire-form. It is
the substrate behind the assertion in the schema-file's `description`
that "third-party implementers SHOULD validate against the test-vector
set before claiming v1 conformance".

## What conformance means here

A v1-conforming verifier MUST:

1. Reject every test-vector in
   [`tooling/external-verifier-ajv/test-vectors.json`](../tooling/external-verifier-ajv/test-vectors.json)
   marked `"expect": "reject"`.
2. Accept every vector marked `"expect": "accept"`.
3. Reach the same per-vector verdict as at least two of the three
   reference validators listed in §3 below.

That is the floor. Implementations that go further (e.g. integrity-
rebuild, OTS-anchor check, signature-slot consumer) are encouraged but
are not part of the schema-correctness contract; see §6.

## §1 — Why three reference validators

Schema correctness is meaningless if the only validator that confirms
it is the one we ourselves wrote. The three reference validators in
this repo come from disjoint codebases:

| Tool                    | Language | Library          | Code path                                 |
|-------------------------|----------|------------------|-------------------------------------------|
| `python-jsonschema`     | Python   | `jsonschema` 4.x | Interpreter over schema dict              |
| `ajv`                   | Node.js  | `ajv` 8.x        | Compile-to-JavaScript via AOT codegen     |
| `python-fastjsonschema` | Python   | `fastjsonschema` | Compile-to-Python via AOT codegen         |

A schema-correctness bug that only affects one library's
Draft-2020-12 implementation becomes visible the moment the N-way
parity check goes red. The driver
[`scripts/external_verifier_validation.py`](../scripts/external_verifier_validation.py)
exits non-zero on any mismatch.

## §2 — How to run the conformance set yourself

```sh
# From a clean repo clone:
pip install jsonschema fastjsonschema
(cd tooling/external-verifier-ajv && npm install)
python scripts/external_verifier_validation.py
```

Expected output footer:

```
cross-tool parity OK (31 vectors, 3 validators: ajv, python-fastjsonschema, python-jsonschema)
```

Subset modes (useful for adoption-time CI):

```sh
# Python-only (no Node.js dependency)
python scripts/external_verifier_validation.py --python-only

# Hard-fail if Node.js side cannot run (CI mode)
python scripts/external_verifier_validation.py --require-node --require-fastjsonschema

# Run against your own vectors file
python scripts/external_verifier_validation.py --vectors my-vectors.json
```

## §3 — The vector-set surface (Sprint-6 Tag-1)

31 vectors today: 9 accept + 22 reject. Coverage by category:

| Category                          | Accept | Reject | Notes                                  |
|-----------------------------------|--------|--------|----------------------------------------|
| Minimal happy-path                | 2      | 0      | string-leaves + object-leaves          |
| Anchor-height variants            | 2      | 1      | accept: 800123 + 2100000; reject: 0    |
| Prev-hour-root variants           | 2      | 1      | accept: hex + null; reject: truncated  |
| Multi-event happy-path            | 1      | 0      | three-event Merkle rebuild target      |
| Duplicate-leaf semantic-ok        | 1      | 0      | same leaf twice; schema does not block |
| Version-enum closure              | 0      | 2      | missing + unknown version-string       |
| Required-field absence            | 0      | 2      | missing-merkle-root + missing-event-id |
| Empty-string defence              | 0      | 1      | empty event_id rejected (minLength: 1) |
| Hex-pattern enforcement           | 0      | 6      | merkle-root, leaf-hash, payload-hash,  |
|                                   |        |        | tree-level entries, uppercase guard    |
| Type-mismatch defence             | 0      | 3      | non-string merkle, non-array events,   |
|                                   |        |        | non-array tree_levels                  |
| AdditionalProperties closure      | 0      | 1      | reject unknown top-level property      |
| Object-leaves shape pin           | 0      | 1      | leaves[].leaf_hash required when obj   |
| Hour-slot pattern                 | 0      | 1      | reject "YYYY-MM-DD HH" (no T)          |
| Event-count domain                | 0      | 1      | reject negative event_count            |
| **Total**                         | **9**  | **22** | **31 vectors**                         |

The vector set is intentionally not exhaustive over every conceivable
malformed manifest — it is engineered to pin the design intent. New
schema-correctness bugs that escape this set should be added as
vectors before the schema is patched, so the regression-prevention
contract is explicit.

## §4 — Adding a fourth-language validator

The vector-set is a single JSON array. Any language with a
Draft-2020-12-conformant JSON-Schema validator can join the parity
check:

1. Read `tooling/external-verifier-ajv/test-vectors.json`.
2. Validate each `manifest` against
   `wirelang/schemas/wakir-wat-manifest-v1.json`.
3. Emit a JSON report identical in shape to `validate.js`:

   ```json
   {
     "tool": "<your-validator-id>",
     "schema_id": "https://wakir.dev/wirelang/schema/wakir-wat-manifest-v1/0.2.0",
     "total": 31,
     "matched": 31,
     "mismatched": 0,
     "results": [
       { "name": "v1-minimal-string-leaves",
         "expect": "accept", "verdict": "accept",
         "matched": true, "errors": [] },
       ...
     ]
   }
   ```

4. Wire your validator into
   [`scripts/external_verifier_validation.py`](../scripts/external_verifier_validation.py)
   alongside `run_python_validator`, `run_node_validator`, and
   `run_fastjsonschema_validator`. The N-way comparison helper
   `compare_reports_multi` is variadic and needs no two-validator
   assumption.

Suggested fourth-language candidates (no preference, boring-tech
choices):

- **Rust**: `jsonschema` crate
- **Java**: `json-schema-validator` (networknt)
- **Go**: `santhosh-tekuri/jsonschema`

Each adds an independent code-path that strengthens the parity-OK
signal linearly.

## §5 — Conformance statement template

A third-party verifier claiming v1 conformance MAY publish:

```text
This verifier conforms to wakir-wat-manifest-v1 schema-version
0.2.0 ($id https://wakir.dev/wirelang/schema/wakir-wat-manifest-v1/0.2.0)
against the Sprint-6 Tag-1 conformance vector set (31 vectors, sha256:
<sha-of-test-vectors.json>). All 31 vectors produce the verdict
declared in the `expect` field.

Verifier: <name + version>
Reference: <commit / URL of validator source>
Cross-tool parity: OK with <list of additional libraries / stacks>
Date: <ISO-8601>
```

A passing claim does not bind Wakir Labs to the third-party verifier
in any way; it is a self-asserted conformance signal that downstream
consumers can verify by re-running the vectors against the same
schema. See `LICENSE` for the underlying licence (Apache-2.0).

## §6 — Beyond schema-validation (out of scope here)

Schema validation is the floor for a v1 verifier. A complete verifier
also performs:

- **Integrity rebuild**: recompute leaves from the B1-tuple per event,
  recompute the Merkle tree, compare against `merkle_root` and
  `tree_levels`. Reference implementation:
  [`wat/verify/manifest_v2.py`](../wat/verify/manifest_v2.py)
  (specifically `_check_real_integrity`).
- **OTS-anchor check**: read sibling `root.bin.ots`, parse as
  OpenTimestamps proof, walk the calendar attestations. Reference:
  same module, `check_ots_anchor`.
- **Signature consumption** (optional v0.2.0 slot): when the
  manifest carries the `signature` top-level field, verify the
  detached Ed25519 signature against the public-key referenced by
  `kid`. Reference: `wat.identity.manifest_signing` +
  `wat.identity.anchor_kid.resolve_wat_anchor_kid`.

These are not part of the schema-correctness conformance contract,
but a verifier that lands on the floor without them is a
schema-syntax validator, not a manifest verifier.

## §7 — Change log

| Schema version | Sprint            | Substance                                       |
|----------------|-------------------|-------------------------------------------------|
| 0.1.0          | Phase-1b Sprint-2 Tag-6 | Initial formal v1 schema-file                   |
| 0.2.0          | Phase-2 Sprint-5 Tag-1  | Additive signature-slot (Ed25519)               |
| 0.2.0          | Phase-2 Sprint-6 Tag-1  | Test-vector set 17→31; fastjsonschema 3rd pole; |
|                |                   | schema-file `examples`; conformance guide      |

The 0.2.0 schema number remains pinned at 0.2.0 because the Sprint-6
changes are additive to the schema-correctness substrate (more
witnesses, more vectors), not to the schema's accept/reject contract.
A wire-form-breaking change requires a $id bump to 0.3.0 and a
parallel schema-file under the new version path.

— Tomás
