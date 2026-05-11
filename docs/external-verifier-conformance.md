<!--
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
SPDX-License-Identifier: Apache-2.0
-->

# External-Verifier Conformance Guide — wakir-wat-manifest-v1

Status: Phase-2 Sprint-6 Tag-6 (2026-05-12).
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
3. Reach the same per-vector verdict as at least two of the four
   reference validators listed in §1 below.

That is the floor. Implementations that go further (e.g. integrity-
rebuild, OTS-anchor check, signature-slot consumer) are encouraged but
are not part of the schema-correctness contract; see §6.

## §1 — Why four reference validators

Schema correctness is meaningless if the only validator that confirms
it is the one we ourselves wrote. The four reference validators in
this repo come from disjoint codebases:

| Tool                    | Language | Library                  | Code path                                 |
|-------------------------|----------|--------------------------|-------------------------------------------|
| `python-jsonschema`     | Python   | `jsonschema` 4.x         | Interpreter over schema dict              |
| `ajv`                   | Node.js  | `ajv` 8.x                | Compile-to-JavaScript via AOT codegen     |
| `python-fastjsonschema` | Python   | `fastjsonschema`         | Compile-to-Python via AOT codegen         |
| `hyperjump`             | Node.js  | `@hyperjump/json-schema` | Interpreter over schema dict (pure JS)    |

Two Python validators (interpreter + AOT codegen) and two JS validators
(AOT codegen + interpreter) give cross-family AND within-family
witness. A schema-correctness bug that only affects one library's
Draft-2020-12 implementation becomes visible the moment the N-way
parity check goes red. The driver
[`scripts/external_verifier_validation.py`](../scripts/external_verifier_validation.py)
exits non-zero on any mismatch.

## §2 — How to run the conformance set yourself

```sh
# From a clean repo clone:
pip install jsonschema fastjsonschema
(cd tooling/external-verifier-ajv && npm install)
(cd tooling/external-verifier-hyperjump && npm install)
python scripts/external_verifier_validation.py
```

Expected output footer:

```
cross-tool parity OK (31 vectors, 4 validators: ajv, hyperjump, python-fastjsonschema, python-jsonschema)
```

Subset modes (useful for adoption-time CI):

```sh
# Python-only (no Node.js dependency)
python scripts/external_verifier_validation.py --python-only

# Hard-fail if every pole must run (strict CI mode)
python scripts/external_verifier_validation.py \
    --require-node --require-fastjsonschema --require-hyperjump

# Skip the fourth (Hyperjump) pole only
python scripts/external_verifier_validation.py --skip-hyperjump

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

## §4 — Adding a fifth-language validator

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
   alongside `run_python_validator`, `run_node_validator`,
   `run_fastjsonschema_validator`, and `run_hyperjump_validator`. The
   N-way comparison helper `compare_reports_multi` is variadic and
   needs no fixed-arity validator-set assumption.

Suggested fifth-language candidates (no preference, boring-tech
choices that cross the language-family boundary):

- **Rust**: `jsonschema` crate
- **Java**: `json-schema-validator` (networknt)
- **Go**: `santhosh-tekuri/jsonschema`

Each adds an independent code-path that strengthens the parity-OK
signal linearly. The four existing poles cover the Python and JS
families two-deep each (interpreter + AOT in both); a Rust/Go/Java
fifth pole is the next strengthening step (see §9).

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

## §7 — Real-cohort driver-mode (Sprint-6 Tag-2)

The synthetic vector set in §3 pins schema-correctness. The
**real-cohort driver-mode** pins the same schema *and* the rest of the
verifier pipeline (integrity rebuild + OTS-anchor side-files + optional
signature consumer) against actual Bitcoin-anchored production hour-
receipts committed under `tests/fixtures/wat-tv2-real/` and
`tests/fixtures/wat-tv3-real/`.

### §7.1 — Schema-parity over the TV cohort

```sh
# TV-2 cohort: 4 hour-receipts, multi-hour chain (2026-05-27T00..T03)
python scripts/external_verifier_validation.py --real-tv2

# TV-3 cohort: 1 hour-receipt, single-hour close-out (2026-05-26T17)
python scripts/external_verifier_validation.py --real-tv3
```

Each hour-receipt's `manifest.json` is wrapped as an accept-vector and
fed through every configured schema validator (§1) plus the in-tree
`verify_real_manifest_file` pipeline. Expected footer:

```
real-tv2 cross-tool parity OK (4 vectors, 3 validators: ...)
verify_real_manifest_file pipeline OK (4 hour-receipts, all green)
```

### §7.2 — Signature-aware driver (`--verify-signature`)

Sprint-6 Tag-2 adds `--verify-signature` to the `--real-tvN` driver.
The production aggregator does not yet emit signed manifests
(Sprint-5 Tag-5 open-item); the driver fills the gap by hand-signing
in-memory deep-copies of every hour-receipt with a fresh ephemeral
Ed25519 keypair, writing them to a tmp directory next to byte-for-byte
copies of the `root.bin` + `root.bin.ots` side-files, then re-running
the verifier pipeline against the staged signed cohort with
`verify_signature=True`. The original repo fixtures are NOT mutated;
the tmp directory is reaped at process exit.

```sh
# TV-2 cohort, signature gate exercised end-to-end.
python scripts/external_verifier_validation.py --real-tv2 --verify-signature

# Same plus VerifyMode.STRICT (rejects unsigned manifests — accepts
# every hour here because the staged cohort is freshly signed).
python scripts/external_verifier_validation.py --real-tv2 \
    --verify-signature --verify-signature-strict
```

Expected footer additions:

```
verify_real_manifest_file (signed cohort) OK (4 hour-receipts, signature_status=['verified'])
```

Per-hour result dicts in the in-memory report carry the
`signature_status` field on both the unsigned and signed paths (empty
string on unsigned, one of `"verified" / "mismatch" / "unsigned-strict"
/ "unsigned-permissive" / "structural-error"` on signed).

### §7.3 — Driver-mode contract

The `--real-tvN --verify-signature` driver-mode is the Brand-Demo TV-2
external-verifier substrate: a third-party can verify our published
hour-receipts with a single CLI invocation that exercises every gate
(schema-file parity across three validators + integrity rebuild +
OTS-anchor side-files + signature). When the production aggregator
gains its own signing branch (Sprint-6+ follow-up), the driver becomes
a no-op wrapper that just points at the on-disk signed manifests
directly; the signature-gate code path is identical.

Misuse guards:

- `--verify-signature` without `--real-tv2` / `--real-tv3` exits with
  rc=2 (synthetic vector mode does not stage signed copies).
- `--verify-signature-strict` without `--verify-signature` exits with
  rc=2 (flag composition).

## §8 — Change log

| Schema version | Sprint                  | Substance                                              |
|----------------|-------------------------|--------------------------------------------------------|
| 0.1.0          | Phase-1b Sprint-2 Tag-6 | Initial formal v1 schema-file                          |
| 0.2.0          | Phase-2 Sprint-5 Tag-1  | Additive signature-slot (Ed25519)                      |
| 0.2.0          | Phase-2 Sprint-6 Tag-1  | Test-vector set 17→31; fastjsonschema 3rd pole;        |
|                |                         | schema-file `examples`; conformance guide              |
| 0.2.0          | Phase-2 Sprint-6 Tag-2  | `--real-tvN --verify-signature` driver-mode;           |
|                |                         | `stage_signed_cohort` helper; signature_status pin     |
| 0.2.0          | Phase-2 Sprint-6 Tag-6  | Fourth validator pole `@hyperjump/json-schema`;        |
|                |                         | JS-family witness now two-deep (ajv + hyperjump)       |

The 0.2.0 schema number remains pinned at 0.2.0 because the Sprint-6
changes are additive to the schema-correctness substrate (more
witnesses, more vectors, more verifier-pipeline coverage), not to the
schema's accept/reject contract. A wire-form-breaking change requires
a $id bump to 0.3.0 and a parallel schema-file under the new version
path.

## §9 — Fourth-pole expansion (Sprint-6 Tag-6)

Sprint-6 Tag-6 extended the cross-tool parity surface from three to
four validators by adding `@hyperjump/json-schema` under
[`tooling/external-verifier-hyperjump/`](../tooling/external-verifier-hyperjump/).

### §9.1 — Why Hyperjump and not Rust/Go/Java

The original Sprint-6 Tag-6 mandate targeted a Rust, Go, or Java
fourth pole for **second-language-family witness** beyond Python and
JS. Pragmatic substitution was forced by sandbox-host environment
constraints: none of `cargo`, `rustc`, `go`, or `java` are present on
the build host and the sandbox is not permitted to install system
packages. Bootstrapping a foreign-language toolchain inside the
box-time window was not feasible without making the choice
operator-driven.

The substitution preserves cross-library-witness substance with the
following trade-off:

- **What is preserved.** Hyperjump (Jason Desrosiers) is an
  independently-maintained Draft-2020-12 implementation that is
  listed by JSON-Schema-Org as a reference implementation. It does
  not share code lineage with ajv. The JS family now has two-deep
  parity (ajv: AOT codegen; Hyperjump: interpreter), mirroring the
  Python family's two-deep parity (jsonschema: interpreter;
  fastjsonschema: AOT codegen). A schema interpretation that ajv and
  Hyperjump disagree on is a real schema-side ambiguity, not an
  ajv-peculiarity.
- **What is deferred.** Second-language-family witness (a non-Python,
  non-JS implementation) remains an open follow-up. Drop-in points in
  the driver (`run_*_validator`) and CLI flag-class (`--skip-*` /
  `--require-*`) are designed for additive extension; a Rust /
  Go / Java pole can join without touching the four-pole code paths.

### §9.2 — Driver wire-up

| Source                                                                                       | Function                       | Skip flag             | Require flag             |
|----------------------------------------------------------------------------------------------|--------------------------------|-----------------------|--------------------------|
| `scripts/external_verifier_validation.py::run_python_validator`                              | python-jsonschema              | `--node-only`         | (always available)       |
| `scripts/external_verifier_validation.py::run_node_validator`                                | ajv                            | `--python-only`       | `--require-node`         |
| `scripts/external_verifier_validation.py::run_fastjsonschema_validator`                      | fastjsonschema                 | `--skip-fastjsonschema` | `--require-fastjsonschema` |
| `scripts/external_verifier_validation.py::run_hyperjump_validator` *(Sprint-6 Tag-6)*        | hyperjump                      | `--skip-hyperjump`    | `--require-hyperjump`    |

Each `run_*_validator` returns either a uniform report dict (matching
the JSON shape in §4) or `None`. The N-way comparator
`compare_reports_multi` consumes the participating subset.

### §9.3 — Foreign-language fifth pole follow-up

Re-opened as an operator-host / Phase-1c task. Acceptance criteria:

1. Choose Rust (`jsonschema` crate), Go (`gojsonschema` /
   `santhosh-tekuri/jsonschema`), or Java
   (`networknt/json-schema-validator`).
2. Drop a `tooling/external-verifier-<lang>/` directory with a
   minimal validator that emits the §4 JSON-report shape.
3. Add `run_<lang>_validator` to
   `scripts/external_verifier_validation.py` with matching
   `--skip-<lang>` / `--require-<lang>` flags.
4. Add a sibling test stanza to
   `tests/wat/test_external_verifier_parity.py` (skip-guard +
   accept-vector pin + pairwise parity pin + N-way parity bump from
   four to five validators).

— Tomás
