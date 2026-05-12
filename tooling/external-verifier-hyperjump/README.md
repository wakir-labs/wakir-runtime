<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- Copyright (c) 2026 Callandor GmbH and contributors -->

# tooling/external-verifier-hyperjump

Fourth-pole cross-tool parity validator for `wakir-wat-manifest-v1`
JSON-Schema.

## Why a fourth pole

The first three poles
([python-jsonschema](https://python-jsonschema.readthedocs.io/),
[ajv](https://ajv.js.org/), and
[fastjsonschema](https://github.com/horejsek/python-fastjsonschema))
cover two Python implementations and one JS implementation.
Cross-tool parity is a stronger signal when both languages have
**two-deep witness**: a verdict drift between two implementations in
the same language reveals a real schema-side ambiguity, not a
shared-implementation peculiarity.

[@hyperjump/json-schema](https://json-schema.hyperjump.io/) (Jason
Desrosiers) is a separately-maintained pure-JS Draft-2020-12
implementation listed by JSON-Schema-Org as a reference
implementation. It is NOT a fork of ajv: ajv compiles the schema to
JavaScript via AOT codegen; Hyperjump interprets the schema directly
and supports declarative composition (`registerSchema` / async
`validate`) that ajv does not.

A verdict drift between ajv and Hyperjump on the same vector set is
a real schema-correctness signal.

## What this directory is NOT

This is not the second-language-family pole. The original Sprint-6
Tag-6 mandate targeted Rust, Go, or Java for second-language-family
witness; the sandbox host has none of those toolchains installed
(no `cargo`, `go`, or `java` on PATH) and no privilege to install
system packages. Hyperjump is the substance-preserving in-scope
substitution. The Rust/Go/Java pole remains an open follow-up — see
[`docs/external-verifier-conformance.md`](../../docs/external-verifier-conformance.md)
§9 for the substitution rationale and §4 for the fifth-pole drop-in
contract.

## Files

- `package.json` — pins `@hyperjump/json-schema`; no other runtime deps.
- `validate.js` — Node.js CLI; loads the schema and a vectors file,
  prints a JSON report with per-vector verdicts, exits non-zero on
  mismatch with the declared `expect` field.

The vector-set is read from
[`../external-verifier-ajv/test-vectors.json`](../external-verifier-ajv/test-vectors.json)
by default — both Node.js poles consume the same authoritative set.

## Install

```sh
cd tooling/external-verifier-hyperjump
npm install
```

`node_modules/` is git-ignored (Node.js convention).

## Run

```sh
# Direct run, prints full JSON report to stdout
node validate.js

# Custom paths
node validate.js \
  --schema=../../wirelang/schemas/wakir-wat-manifest-v1.json \
  --vectors=../external-verifier-ajv/test-vectors.json
```

Exit codes: `0` all matched, `1` at least one vector mismatched its
expected verdict, `2` CLI / file-loading error.

## Cross-tool parity (the actual contract)

Driven by
[`scripts/external_verifier_validation.py`](../../scripts/external_verifier_validation.py)
with N-way parity. Hyperjump-only flag-class:

- `--skip-hyperjump` — silently skip this pole.
- `--require-hyperjump` — hard-fail when the pole cannot run
  (no `node`, or this directory's `node_modules/` is absent).

See the [conformance guide](../../docs/external-verifier-conformance.md)
§1 for the full validator matrix and §9 for the fourth-pole
expansion rationale.

## License

Apache License 2.0; see [../../LICENSE](../../LICENSE).
