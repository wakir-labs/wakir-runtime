<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# `make demo-proof` — Operator Runbook

Runs the full Wakir evidence chain end-to-end as a single command and
emits a JSON report describing the outcome per leg plus the cross-repo
commit pins the demo executed against.

This runbook is the operator-facing companion to
`scripts/demo-proof.sh` and `scripts/demo_proof_helpers.py`. The
driver needs `bash` and `python3`, nothing else; all JSON handling is
in the Python helper. Tests in `tests/scripts/test_demo_proof.py`
exercise the same code paths, with and without `jq` on PATH.

## When to run

- An external reviewer asks for a reproducible proof that the three
  repos (`wakir-protocol` / `wakir-runtime` / `wakir-verify`) glue
  together, without a separate demo of each piece.
- A pre-merge sanity check after touching any of the legs the demo
  exercises (B1 leaf shape, bridge writer, aggregator, inclusion
  proof, external verifier surface).
- As the CI proof-path gate (see "CI integration").

The demo is **not** a load test, **not** a security audit, and
**not** a substitute for the live-VM acceptance gate.

## Quick start

```sh
make demo-proof
```

The script allocates a tmpdir, runs the five steps, and prints the
JSON report on stdout. Exit code 0 means no step failed; 10 means at
least one step `failed` (see the per-step `status` field).

For the cross-repo leg to be a real `ok`, install `wakir-verify` into
the Python environment that `python3` resolves to:

```sh
pip install git+https://github.com/wakir-labs/wakir-verify
make demo-proof
```

To capture the report:

```sh
make demo-proof | tee /tmp/wakir-demo-proof-$(date -u +%Y%m%dT%H%M%SZ).json
```

## Configuration

All knobs are environment variables.

| Variable                     | Default                          | Effect                                                                 |
| ---------------------------- | -------------------------------- | ---------------------------------------------------------------------- |
| `DEMO_PROOF_WORKDIR`         | fresh `mktemp -d` under `$TMPDIR`| Where step artefacts are written. Override for reproducible runs.      |
| `DEMO_PROOF_HOUR`            | `2026-05-17T12`                  | UTC hour slot used for the demo event. Pinned for reproducibility.     |
| `DEMO_PROOF_VERIFY_ONLINE`   | `0`                              | When `1` *and* an OTS receipt is given, step 5 also runs the console script (network). |
| `DEMO_PROOF_OTS_PROOF`       | unset                            | Path to a real `.ots` receipt. `ONLINE=1` without it is an explicit `skipped`. |
| `DEMO_PROOF_VERIFY_CMD`      | `wakir-verify`                   | Console-script name or path, online mode only.                         |
| `DEMO_PROOF_PROTOCOL_COMMIT` | `unknown`                        | Optional commit-hash pin for `wakir-protocol` (recorded in report).    |
| `DEMO_PROOF_VERIFY_COMMIT`   | `unknown`                        | Optional commit-hash pin for `wakir-verify` (recorded in report).      |
| `DEMO_PROOF_TEST_MODE`       | `0`                              | `1` enables the two test hooks below. Off in production runs.          |
| `DEMO_PROOF_FAIL_STEP`       | unset                            | Test hook: step function to fail, e.g. `step3_merkle_manifest`.        |
| `DEMO_PROOF_SIMULATE_NO_WAKIR_VERIFY` | `0`                     | Test hook: treat `wakir_verify` as not installed.                      |

The runtime repo commit hash is resolved from the current `git HEAD`;
there is no override for it on purpose.

## Output schema

```json
{
  "schema": "wakir-demo-proof/v1",
  "hour": "2026-05-17T12",
  "workdir": "/tmp/wakir-demo-proof.XXXXXX",
  "commits": {
    "wakir_runtime":  "<git rev-parse HEAD>",
    "wakir_protocol": "<DEMO_PROOF_PROTOCOL_COMMIT or 'unknown'>",
    "wakir_verify":   "<DEMO_PROOF_VERIFY_COMMIT or 'unknown'>"
  },
  "steps": [
    {
      "name": "protocol_event",
      "status": "ok" | "failed" | "skipped" | "not_run",
      "exit_code": 0 | 10 | 20 | 30,
      "details": { ... step-specific ... }
    },
    { "name": "runtime_bridge",   ... },
    { "name": "merkle_manifest",  ... },
    { "name": "inclusion_proof",  ... },
    { "name": "external_verify",  ... }
  ],
  "exit_code": 0 | 10
}
```

All five step names are always present, in this order. Per-step codes:

| Code | Status    | Meaning                                                            |
| ---- | --------- | ------------------------------------------------------------------ |
| 0    | `ok`      | Leg passed.                                                        |
| 10   | `failed`  | Substance error; the run short-circuits after this step.           |
| 20   | `skipped` | Leg intentionally not exercised; `details.reason` says why.        |
| 30   | `not_run` | Downstream of a failure; `details.reason` names the failed step.   |

Process exit code: 0 when no step is `failed` (so `skipped` does not
fail the demo — a fresh clone without wakir-verify exits 0), 10 when
any step is `failed`, 2 when `python3` is missing. The CI gate layers
`external_verify == ok` on top through the report validator.

## What each step does

### Step 1 — `protocol_event`

Builds a B1-canonical Wirelang demo event with the four required
fields (`event_id`, `time`, `payload_hash`, `capability_token_hash`).
The payload is a deterministic JSON object, so the resulting
`payload_hash` is reproducible. Written to
`${DEMO_PROOF_WORKDIR}/event.json` plus the sidecar
`event.envelope.json` used by step 4.

### Step 2 — `runtime_bridge`

Invokes `wat.anchor.bridge_audit_writer.write_bridge_audit` against
the temp spool root and temp activity log — the same code path the
production bridge uses. The result JSON records the bridge status.

Note: the bridge rewrites `event_id` into a deterministic
SHA-256-derived 32-hex string. Step 4 matches the demo event by
`payload_hash`, which the bridge passes through unchanged.

### Step 3 — `merkle_manifest`

Projects the spool record into the aggregator's `--input-events`
JSONL shape and drives `wat.cmd.aggregator_cli.build_command`.
Output: `${DEMO_PROOF_WORKDIR}/${DEMO_PROOF_HOUR}/manifest.json`
(`wakir-wat-manifest/v1`).

### Step 4 — `inclusion_proof`

Recomputes the leaf hash for every manifest row, locates the demo
event, builds the sibling path with `wat.merkle.aggregator.merkle_proof`
and verifies it against the stored root. Output:
`${DEMO_PROOF_WORKDIR}/proof.json`, a `wakir-inclusion-proof/v1`
document (schema draft: `wirelang/schemas/wakir-inclusion-proof-v1.json`).

To check it by hand: start with `leaf_hash`; for each entry of
`siblings` in order compute `SHA-256(sibling || current)` when
`side == "L"` or `SHA-256(current || sibling)` when `side == "R"`;
the result must equal `merkle_root`. A single-leaf tree has an empty
`siblings` list and `leaf_hash == merkle_root`.

### Step 5 — `external_verify`

Cross-repo leg through the `wakir-verify` **library**: the manifest
is loaded with `wakir_verify.manifest.load_manifest_from_file`, its
root re-derived with `compute_manifest_consistency`, and the step-4
proof checked with `wakir_verify.merkle_proof.verify_merkle_proof`.
No network is involved.

- `wakir_verify` importable → `ok` (or `failed` if any check is
  false; `details` lists `manifest_consistent`, `root_match`,
  `leaf_present`, `proof_verified`).
- `wakir_verify` not importable → `skipped` with `details.reason`.
  The in-tree root re-derivation still runs
  (`details.local_root_rederived`) but cannot turn the step green.
- `DEMO_PROOF_VERIFY_ONLINE=1` with `DEMO_PROOF_OTS_PROOF` → the
  library check runs first, then the console script is driven with
  `--anchor <merkle_root> --ots-proof <receipt> --output-format json`
  (Bitcoin network access). `ONLINE=1` without a receipt is an
  explicit `skipped`.

## Failure recovery

Re-running from a fresh `DEMO_PROOF_WORKDIR` produces byte-identical
artefacts. To debug a failed leg:

1. Re-run with `DEMO_PROOF_WORKDIR=/tmp/wakir-demo-proof-debug` so
   artefacts persist.
2. The failed step's stderr is in `details.error` of its report
   record and in `${DEMO_PROOF_WORKDIR}/stepN.err`.
3. Per-step result JSON sits next to it (`bridge-result.json`,
   `proof.json`, `verify-result.json`).
4. `${DEMO_PROOF_WORKDIR}/demo-report.json` is what the script
   printed on stdout.

## CI integration

`tests/scripts/test_demo_proof.py` covers the helper functions, the
bash driver (including fault injection via the test hooks) and the
proof format. The proof-path workflow runs `make demo-proof` with
`wakir-verify` installed and validates the report with
`external_verify == ok` required.
