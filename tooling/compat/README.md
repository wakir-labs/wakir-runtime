<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Cross-repo compatibility gate (protocol ↔ runtime ↔ verify)

Workflow: `.github/workflows/cross-repo-compat.yml`, job display name
`cross-repo compatibility (protocol ↔ runtime ↔ verify)`. Fires on every
pull request and every push to `main`, no path filter. Enforcing from
day one — there is no audit-only mode.

It replaces the byte-level `cross-repo-drift-audit` (SHA-256 over 10
file pairs, never enforced) with four substantive levels. wakir-protocol
is the canonical home of schemas, test vectors and the proof format;
wakir-runtime mirrors, wakir-verify consumes.

| Level | Runtime side | Protocol / verify side | Red when |
|---|---|---|---|
| schema | `wirelang/schemas/*.json` | `wakir_protocol/schemas/*.json` | canonical digest differs, counterpart missing |
| vector | `wat.merkle.aggregator` | `tests/fixtures/proof-path-vectors/vector-*.json`, `wakir_verify.merkle_proof` | leaf hash, level, root or sibling path differs; tampered leaf verifies |
| manifest | aggregator output of `make demo-proof`, `wat.verify.cli` | `wakir-wat-manifest-v1.json`, `wakir_verify.manifest` | schema violation, `MANIFEST_VERSION` not in `$id`/enum, loader root mismatch, constraint C1 broken |
| proof | `proof.json` of `make demo-proof` | `wakir-inclusion-proof-v1.json`, `wakir_verify.merkle_proof` | schema violation, proof does not resolve to the manifest root |

## Canonicalisation rule (shared with wakir-protocol)

1. Parse the schema as JSON.
2. Remove **at every nesting level** every key that starts with
   `x-spdx-` (licence-header extension keys differ by design) or
   equals `description` (prose).
3. JCS (RFC 8785) via `rfc8785.dumps`.
4. SHA-256, lower-case hex.

Everything else (`enum`, `const`, `required`, `pattern`, `$id`,
`title`, `additionalProperties`, ...) is contract and stays in the
digest. Stripping only at the top level is not enough: on
2026-09-11 (protocol `b7de631`) that left 7/16 schemas red on prose;
recursive stripping gives 16/16 green.

```
python3 tooling/compat/compat_canonical.py wirelang/schemas/*.json
```

A protocol schema marked `"x-status": "stub"` is not compared
(`deferred`) — the comparison arms itself the moment the canonical
file lands.

## Allowlist (`compat-allowlist.json`)

```json
{
  "schema": "wakir-compat-allowlist/v1",
  "entries": [
    {"path": "wirelang/schemas/example.json",
     "until": "2026-09-30",
     "tracking": "https://github.com/wakir-labs/wakir-runtime/pull/123",
     "reason": "optional"}
  ]
}
```

`path` is the runtime-side repo-relative path, exact match. `until`
is mandatory; expired entries fail the gate. `tracking` must be a
GitHub PR or issue URL. Unused entries are reported as `warn`.
Legitimate schema evolution = version bump in protocol + time-boxed
allowlist entry here + mirror PR; never byte tolerance.

## Constraint C1 (manifest level)

The runtime aggregator writes `version` + `hour_slot`; the
`wakir_verify.manifest` loader reads the *optional* `envelope`
(default `""`) + `hour` (default `None`) and ignores `version` /
`hour_slot`. Both sides agree on `merkle_root` and
`leaves[].{event_id, leaf_hash}`. The gate pins exactly this state:
if either side starts emitting/reading the other's field, the value
must equal its counterpart or the manifest level goes red.

## Running locally

```
python3 -m venv .venv && . .venv/bin/activate
pip install -e . -e ../wakir-verify "jsonschema>=4.21"
DEMO_PROOF_WORKDIR=/tmp/demo make demo-proof
python3 tooling/compat/check_compat.py \
    --protocol ../wakir-protocol --verify ../wakir-verify \
    --demo-workdir /tmp/demo --summary-md /tmp/compat.md
```

Hermetic tests for the tooling (mock checkouts, no network):
`python -m pytest tests/compat -q`.

## Proving the gate bites

Copy the protocol checkout, change one enum value in any mirrored
schema (for example `sibling.side` in
`wakir_protocol/schemas/wakir-inclusion-proof-v1.json` once it is
canonical, or `version.enum` in `wakir-wat-manifest-v1.json`), rerun
`check_compat.py --protocol <copy>`: the schema level reports
`canonical drift` and the exit code is 1.
