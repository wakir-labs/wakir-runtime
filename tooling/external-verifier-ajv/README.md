<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# tooling/external-verifier-ajv

Cross-tool parity validator for `wakir-wat-manifest-v1` JSON-Schema.

## Why

The formal schema file
[`wirelang/schemas/wakir-wat-manifest-v1.json`](../../wirelang/schemas/wakir-wat-manifest-v1.json)
is the contract handed to third-party verifier implementers. Schema
correctness is meaningless if the only validator that confirms it is
the one we ourselves wrote. This directory is the second-implementation
half of the parity contract: a Node.js + [ajv](https://ajv.js.org/)
validator that runs the same test-vector set as the Python
`jsonschema` reference and asserts identical per-vector verdicts.

When the verdicts disagree, the schema is ambiguous between
implementations and must be tightened **before** it lands in any
third-party hands. Cross-tool parity gives the schema-correctness
conversation objective ground truth.

## Files

- `package.json` — pins `ajv` and `ajv-formats`; no other runtime deps.
- `validate.js` — Node.js CLI; loads the schema and a vectors file,
  prints a JSON report with per-vector verdicts, exits non-zero on
  mismatch with the declared `expect` field.
- `test-vectors.json` — the shared test-vector set. **Authoritative**:
  both the Python `jsonschema` smoke-test
  ([tests/wat/test_manifest_v1_schema_smoke.py](../../tests/wat/test_manifest_v1_schema_smoke.py))
  and the Node.js / ajv side consume vectors from here. Edit this
  file and **both sides** run the new vectors automatically.

Each vector has the shape:

```json
{
  "name": "v1-minimal-string-leaves",
  "expect": "accept" | "reject",
  "manifest": { ... wakir-wat-manifest/v1 wire-form ... }
}
```

## Install

```sh
cd tooling/external-verifier-ajv
npm install
```

`node_modules/` is in `.gitignore` (Node.js convention). The
`package.json` pins major versions so re-installation produces a
predictable validator.

## Run

```sh
# Direct run, prints full JSON report to stdout
node validate.js

# Custom paths
node validate.js \
  --schema=../../wirelang/schemas/wakir-wat-manifest-v1.json \
  --vectors=test-vectors.json
```

Exit codes: `0` all matched, `1` at least one vector mismatched its
expected verdict, `2` CLI / file-loading error.

## Cross-tool parity (the actual contract)

The reference driver is
[`scripts/external_verifier_validation.py`](../../scripts/external_verifier_validation.py).
It runs three validators (one Node.js, two Python) and compares
per-vector verdicts in an N-way parity check:

```sh
python scripts/external_verifier_validation.py
```

Configured validators (Sprint-6 Tag-6):

| Tool                       | Language | Library                  | Role                  |
|----------------------------|----------|--------------------------|-----------------------|
| `python-jsonschema`        | Python   | `jsonschema` 4.x         | Reference validator   |
| `ajv`                      | Node.js  | `ajv` 8.x                | Cross-stack witness   |
| `python-fastjsonschema`    | Python   | `fastjsonschema`         | Cross-library witness (Python family) |
| `hyperjump`                | Node.js  | `@hyperjump/json-schema` | Cross-library witness (JS family) |

The Python triangulation (`jsonschema` vs. `fastjsonschema`) catches
library-side bugs that a pure Python-vs-Node check would miss; the
JS triangulation (`ajv` vs. `hyperjump`) does the same on the JS
side. Both families are now two-deep, so the parity-OK signal
witnesses both cross-stack AND within-stack interpretation
agreement.

The pytest wrapper
[`tests/wat/test_external_verifier_parity.py`](../../tests/wat/test_external_verifier_parity.py)
gates on the same parity contract. Node.js side is `pytest.mark.skipif`
when `node` is unavailable or `node_modules/` is missing;
fastjsonschema side is `skipif` when the library is not installed.
The Python-jsonschema side always runs.

## Adding a fifth validator

The vector format is intentionally portable. To bring a Rust / Java /
Go validator into the parity check (cross-family witness beyond Python
and JS):

1. Read `test-vectors.json`.
2. For each vector, validate `manifest` against the schema.
3. Emit a JSON report with the same shape as `validate.js` (one
   `results[]` entry per vector, with `matched` derived from
   `expect == verdict`).
4. Wire your tool into `scripts/external_verifier_validation.py`'s
   parity-comparison alongside the three existing sides
   (`compare_reports_multi` is N-way, no two-validator-only assumption
   in the comparison helper), or compare reports out-of-band with
   `jq`.

Adding implementations strengthens the schema-correctness signal
linearly; every passing parity check across an additional tool buys
the schema another standards-conformance witness.

See [`docs/external-verifier-conformance.md`](../../docs/external-verifier-conformance.md)
for the adoption guide and the conformance-statement template.

## License

Apache License 2.0; see [../../LICENSE](../../LICENSE).
