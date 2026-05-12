<!--
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
SPDX-License-Identifier: Apache-2.0
-->

# external-verifier-validation(1) — Driver Manpage

Status: Phase-2 Sprint-6 Tag-2 (2026-05-11).
Tool: `scripts/external_verifier_validation.py`
Companion guide: [`external-verifier-conformance.md`](./external-verifier-conformance.md)

## Name

`external_verifier_validation.py` — cross-tool JSON-Schema parity
driver + real-manifest-cohort runner for `wakir-wat-manifest/v1`.

## Synopsis

```
python scripts/external_verifier_validation.py [OPTIONS]
```

## Description

Runs the canonical `wakir-wat-manifest-v1` JSON-Schema validation
across a test-vector set with N independent Draft-2020-12 validators
(Python `jsonschema`, Node.js `ajv`, Python `fastjsonschema`) and
asserts N-way parity. Optionally drives the same validators plus the
in-tree `wat.verify.manifest_v2.verify_real_manifest_file` pipeline
against the on-disk TV-2 (4 hour-receipts) or TV-3 (1 hour-receipt)
real-Bitcoin-anchored fixture cohort. With `--verify-signature` the
real-cohort run also exercises the optional manifest-signature gate
against a freshly-signed in-memory copy of the cohort.

## Modes

### Synthetic vector mode (default)

```sh
python scripts/external_verifier_validation.py
```

Reads `tooling/external-verifier-ajv/test-vectors.json` (31 vectors as
of Sprint-6 Tag-1), validates each against every available validator,
emits per-validator reports and the N-way parity verdict.

### Real-cohort mode

```sh
python scripts/external_verifier_validation.py --real-tv2
python scripts/external_verifier_validation.py --real-tv3
```

Replaces the synthetic vector source with the on-disk hour-receipt
fixtures under `tests/fixtures/wat-tv2-real/` (4 hours) or
`tests/fixtures/wat-tv3-real/` (1 hour). Runs the schema-file
validators AND the `verify_real_manifest_file` pipeline (integrity-
rebuild + OTS-anchor side-files). `--real-tv2` and `--real-tv3` are
mutually exclusive.

### Signature-aware real-cohort mode (Sprint-6 Tag-2)

```sh
python scripts/external_verifier_validation.py --real-tv2 --verify-signature
python scripts/external_verifier_validation.py --real-tv2 --verify-signature --verify-signature-strict
python scripts/external_verifier_validation.py --real-tv3 --verify-signature
```

In addition to the schema-file + pipeline run, hand-signs in-memory
deep-copies of every hour-receipt with a fresh ephemeral Ed25519
keypair, writes the signed cohort to a tmp directory next to byte-for-
byte copies of `root.bin` / `root.bin.ots`, then runs the
`verify_real_manifest_file` pipeline a second time with
`verify_signature=True` against the staged signed cohort. Reports the
per-hour `signature_status` ("verified" on the staged path) and exits
non-zero on any signature-gate failure. The original repo fixtures are
NOT mutated; the tmp directory is reaped at process exit.

## Options

### Vector source

| Flag                          | Effect                                                                         |
|-------------------------------|--------------------------------------------------------------------------------|
| `--vectors PATH`              | Override synthetic vector source (default `tooling/external-verifier-ajv/test-vectors.json`). |
| `--real-tv2`                  | Use the TV-2 on-disk hour-receipt cohort instead.                              |
| `--real-tv3`                  | Use the TV-3 on-disk hour-receipt cohort instead.                              |

### Validator selection

| Flag                          | Effect                                                                         |
|-------------------------------|--------------------------------------------------------------------------------|
| `--python-only`               | Skip Node.js / ajv side.                                                       |
| `--node-only`                 | Skip Python jsonschema side (also skips fastjsonschema).                       |
| `--require-node`              | Hard-fail when `node` is unavailable instead of skipping silently.             |
| `--skip-fastjsonschema`       | Skip the Python fastjsonschema third-pole validator.                           |
| `--require-fastjsonschema`    | Hard-fail when fastjsonschema is not importable.                               |

### Signature gate (real-cohort mode only)

| Flag                          | Effect                                                                         |
|-------------------------------|--------------------------------------------------------------------------------|
| `--verify-signature`          | Stage a signed copy of the cohort and run `verify_real_manifest_file(verify_signature=True, ...)` against it. |
| `--verify-signature-strict`   | Use `VerifyMode.STRICT` (reject unsigned manifests). Requires `--verify-signature`. |

### Output

| Flag                          | Effect                                                                         |
|-------------------------------|--------------------------------------------------------------------------------|
| `--quiet`                     | Suppress per-vector verdict tables; emit only the parity / pipeline footers.   |

## Exit codes

| Code | Meaning                                                                                  |
|------|------------------------------------------------------------------------------------------|
| 0    | Every vector matched its expected verdict in every configured validator; pipeline green. |
| 1    | At least one vector mismatched, or a pipeline hour-receipt failed.                       |
| 2    | CLI / file-loading / Node.js-availability error, or an invalid flag composition.         |

## Invalid flag compositions (exit 2)

- `--python-only` and `--node-only` together.
- `--real-tv2` and `--real-tv3` together.
- `--verify-signature` without `--real-tv2` or `--real-tv3`.
- `--verify-signature-strict` without `--verify-signature`.

## Examples

```sh
# Schema parity over the synthetic vector set, all three validators.
python scripts/external_verifier_validation.py

# Brand-Demo TV-2 substrate: full end-to-end verification (schema
# parity x3 + integrity rebuild + OTS-anchor side-files + signature).
python scripts/external_verifier_validation.py --real-tv2 --verify-signature --quiet

# CI mode: hard-fail without Node.js or fastjsonschema.
python scripts/external_verifier_validation.py --require-node --require-fastjsonschema

# Test your own vectors file against the canonical schema.
python scripts/external_verifier_validation.py --vectors my-vectors.json
```

## See also

- [`external-verifier-conformance.md`](./external-verifier-conformance.md) — adoption guide and §7 driver-mode contract.
- [`wat-manifest-v2-spec.md`](./wat-manifest-v2-spec.md) §11 — change log (Sprint-6 Tag-1 / Tag-2 entries).
- [`tooling/external-verifier-ajv/README.md`](../tooling/external-verifier-ajv/README.md) — Node.js side runner.

— Tomás
