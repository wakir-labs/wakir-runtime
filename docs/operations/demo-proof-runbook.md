<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# `make demo-proof` — Operator Runbook

External-audit walkthrough driver. Runs the full Wakir evidence
chain end-to-end as a single command and emits a JSON report
describing pass/fail per leg plus the three cross-repo commit
pins the demo executed against.

This runbook is the operator-facing companion to
`scripts/demo-proof.sh` and `scripts/demo_proof_helpers.py`. The
script is intentionally self-contained: bash + jq + Python (no
extra host tooling). Tests in `tests/scripts/test_demo_proof.py`
exercise the same code paths.

## When to run

- An external auditor or Aufsichtsrat-Mitglied asks for a
  reproducible proof that the three repos
  (`wakir-protocol` / `wakir-runtime` / `wakir-verify`) actually
  glue together, without you having to demo each piece separately.
- A pre-merge sanity check after touching any of the four legs
  the demo exercises (B1 leaf shape, bridge writer, aggregator,
  inclusion proof, external verifier surface).
- A post-incident credibility-restoration walkthrough — the JSON
  report is short, machine-readable, and shows commit hashes for
  the runtime repo HEAD.

The demo is **not** a load test, **not** a security audit, and
**not** a substitute for the live-VM acceptance gate. It is a
one-command cross-repo demo, nothing more.

## Quick start

```sh
make demo-proof
```

That's it. The script self-allocates a tmpdir, runs the five
steps, and prints the JSON report on stdout. Exit code 0 means
all five legs passed; non-zero means at least one leg failed or
was skipped (see the per-step `status` field).

To capture the report for archival or audit forwarding:

```sh
make demo-proof | tee /tmp/wakir-demo-proof-$(date -u +%Y%m%dT%H%M%SZ).json
```

## Configuration

All knobs are environment variables. Defaults match the hermetic
CI path; operators override the variables when they want a
deterministic or production-mode run.

| Variable                    | Default                          | Effect                                                                |
| --------------------------- | -------------------------------- | --------------------------------------------------------------------- |
| `DEMO_PROOF_WORKDIR`        | per-PID `mktemp -d` tmpdir       | Where step artefacts are written. Override for reproducible runs.     |
| `DEMO_PROOF_HOUR`           | `2026-05-17T12`                  | UTC hour slot used for the demo event. Pinned for reproducibility.    |
| `DEMO_PROOF_VERIFY_CMD`     | `wakir-verify`                   | Command name (or absolute path) for the external verifier console.    |
| `DEMO_PROOF_VERIFY_ONLINE`  | `0`                              | When `1`, the verify step shells out for real. Default keeps it dry.  |
| `DEMO_PROOF_OTS_PROOF`      | unset                            | Path to a real `.ots` receipt; required when `VERIFY_ONLINE=1`.       |
| `DEMO_PROOF_PROTOCOL_COMMIT`| `unknown`                        | Optional commit-hash pin for `wakir-protocol` (recorded in report).   |
| `DEMO_PROOF_VERIFY_COMMIT`  | `unknown`                        | Optional commit-hash pin for `wakir-verify`  (recorded in report).    |

The runtime repo commit hash is resolved automatically from the
current `git HEAD`; there is no override for it on purpose.

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
      "status": "ok" | "failed" | "skipped",
      "exit_code": 0 | 10 | 20,
      "details": { ... step-specific ... }
    },
    { "name": "runtime_bridge",   ... },
    { "name": "merkle_manifest",  ... },
    { "name": "inclusion_proof",  ... },
    { "name": "external_verify",  ... }
  ]
}
```

Per-step exit codes:

| Code | Meaning      | Aggregate behaviour                                   |
| ---- | ------------ | ----------------------------------------------------- |
| 0    | OK           | Downstream steps continue.                            |
| 10   | FAILED       | Short-circuits; the demo aborts after that step.      |
| 20   | SKIPPED      | Downstream steps continue; final exit code is 20.     |

The aggregate exit code is `max(step exit codes)` so a failure
dominates a skip which dominates a clean pass.

## What each step actually does

### Step 1 — `protocol_event`

Builds a B1-canonical Wirelang demo event with the four required
fields (`event_id`, `time`, `payload_hash`,
`capability_token_hash`). The payload is a deterministic JSON
object, so the resulting `payload_hash` is reproducible. The
event envelope is written to
`${DEMO_PROOF_WORKDIR}/event.json` plus an envelope sidecar
`event.envelope.json` for step 4.

### Step 2 — `runtime_bridge`

Invokes `wat.anchor.bridge_audit_writer.write_bridge_audit`
against the temp spool root and temp activity-log. This is the
real bridge writer — the same code path the pilot operator
exercises in production. The result JSON records the bridge
status (`ok` / `wat-failed` / `pre-framework-failed`).

Note: the bridge rewrites `event_id` into a deterministic
SHA-256-derived 32-hex string. The envelope from step 1 carries
the operator-supplied identifier; the manifest records the
bridge's derived one. Step 4 matches them by `payload_hash`,
which the bridge passes through unchanged.

### Step 3 — `merkle_manifest`

Projects the bridge's spool record into the aggregator's
`--input-events` JSONL shape and drives
`wat.cmd.aggregator_cli.build_command`. Output:
`${DEMO_PROOF_WORKDIR}/${DEMO_PROOF_HOUR}/manifest.json` with
the canonical `merkle_root`, `event_count`, and per-event B1
rows.

### Step 4 — `inclusion_proof`

Recomputes the leaf hash for every manifest event, locates the
demo event by `payload_hash`, rebuilds the inclusion proof via
`wat.merkle.aggregator.merkle_proof`, and verifies it against
the stored root using `verify_merkle_proof`. The result JSON
records the proof depth and the verifier's verdict.

### Step 5 — `external_verify`

Two sub-paths:

- **`wakir-verify` installed**: shells out to the sibling
  console script. In default hermetic mode the call is just
  `wakir-verify --help` (proves the cross-repo binary surface
  is wired without touching the network). In online mode
  (`DEMO_PROOF_VERIFY_ONLINE=1` + `DEMO_PROOF_OTS_PROOF=...`)
  the call drives the full 4-pole verifier against the manifest
  anchor; this requires Bitcoin network access.
- **`wakir-verify` not installed**: falls back to a fixture
  verifier that re-derives the manifest root locally via
  `wat.merkle.aggregator.build_merkle_tree`. The step is marked
  `status=skipped` regardless of fallback success so an operator
  cannot mistake it for a real cross-repo pass.

## Failure recovery

The script is idempotent in the sense that re-running it from a
fresh `DEMO_PROOF_WORKDIR` produces byte-identical output. To
debug a failed leg:

1. Re-run with `DEMO_PROOF_WORKDIR=/tmp/wakir-demo-proof-debug`
   so artefacts persist.
2. Inspect the per-step stderr capture under
   `${DEMO_PROOF_WORKDIR}/stepN.err`.
3. The per-step output JSON sits next to the stderr capture
   (e.g. `bridge-result.json`, `proof.json`).
4. The full report at `${DEMO_PROOF_WORKDIR}/demo-report.json`
   matches what the script printed on stdout.

If step 5 falls back to fixture mode but you expected a real
cross-repo run: install `wakir-verify` into the active Python
environment (`pip install wakir-verify`) or set
`DEMO_PROOF_VERIFY_CMD` to an explicit path to the console
script.

## CI integration

The demo is wired into CI via `tests/scripts/test_demo_proof.py`
(hermetic subprocess-mocked path) and an optional shell-driver
smoke test that runs `make demo-proof` against a tmpdir. The
test suite never reaches for the network — `DEMO_PROOF_VERIFY_ONLINE`
stays at `0` in CI, and the fixture-verify fallback handles the
`wakir-verify`-not-installed case deterministically.
