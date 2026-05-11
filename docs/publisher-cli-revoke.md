# `wakir-schema-registry revoke` — Operator Manpage

**Module:** `wirelang.schemas.publisher_cli`
**Subcommand:** `revoke`
**Sprint:** Phase-2 Sprint-6 Tag-2 (additive over Sprint-6 Tag-1
revocation backend axis)
**Bucket touched:** `wakir-capability-policies` (NOT `wakir-schemas`)

---

## Synopsis

```
wakir-schema-registry revoke
  --registered-by <issuer>
  --policy-id <policy-id>
  --revoked-at <rfc3339-with-tz>
  --registered-by-publisher <operator-id>
  [--revocation-reason <free-form>]
  [--registered-at <rfc3339-with-tz>]
  [--expected-revision <int> | --lww]
  [--connect-url <nats-url>]
```

---

## Purpose

Apply an *explicit revocation* to an existing capability-policy
record on the `wakir-capability-policies` NATS-KV bucket. This is
the operator surface for the Sprint-6 Tag-1 backend axis (typed
`revoked_at` + `revocation_reason` on `CapabilityPolicy`; gate
denies `as_of >= revoked_at` with source `POLICY_REVOKED`;
`put_with_revision` enforces revocation-monotonicity).

The subcommand operates on a *single* record identified by the
`(registered_by, policy_id)` pair. It does NOT touch the
`wakir-schemas` schema-registry bucket; that bucket is the consumer
side of the gate, not the policy authoring side.

---

## Flags

### Identity pair (required)

- `--registered-by <issuer>` — `registered_by` of the
  capability-policy record. Must be a kebab-case ASCII string
  matching `^[A-Za-z0-9][A-Za-z0-9_.:\-]*$` (mirror of the
  schema-registry `registered_by` convention).
- `--policy-id <policy-id>` — operator-supplied policy identifier,
  same character class as `registered_by`.

Together they derive the canonical KV key
`capability-policies/<registered_by>/<policy_id>`.

### Revocation payload (required + optional)

- `--revoked-at <rfc3339-with-tz>` (required) — the wall-clock
  instant of the revocation. MUST carry a timezone (e.g.
  `2026-05-11T22:00:00Z` or `2026-05-11T22:00:00+00:00`); a naive
  RFC-3339 is rejected with `INPUT_ERROR` (3). The gate (Sprint-4
  Tag-6 + Sprint-6 Tag-1) denies any decision with
  `as_of >= revoked_at` and source `POLICY_REVOKED`.
- `--revocation-reason <free-form>` (optional but strongly
  recommended) — free-form audit string. Surfaced in the gate's
  deny reason and persisted on the bucket envelope. Use it.

### Audit fields (required + optional)

- `--registered-by-publisher <operator-id>` (required) — the
  operator authoring the revocation. NOT the same as
  `--registered-by` (which names the policy issuer being revoked).
  Recorded on the rewritten record's `registered_by_publisher`
  field for audit purposes.
- `--registered-at <rfc3339-with-tz>` (optional) — overrides the
  rewritten record's `registered_at` timestamp. Defaults to the
  current UTC instant. Test paths and deterministic CI pipelines
  should supply this explicitly so receipts are byte-stable.

### Write mode (mutually exclusive)

- (default, no flag) — **CAS-pin auto-pin**. The CLI reads the
  live revision via `get_with_revision_by_pair` and pins the write
  to that revision. Safest mode.
- `--expected-revision <int>` — **CAS-pin explicit**. The operator
  declares the revision they observed via a prior read. The CLI
  ALSO reads the live revision before the write so the receipt
  always records `previous_revision`; a mismatch between
  `--expected-revision` and the live revision surfaces with
  `CAS_CONFLICT` (5) BEFORE any backend write.
- `--lww` — **last-write-wins escape-hatch**. Bypasses the
  Sprint-6 Tag-1 revocation-monotonic backend invariant. Permits
  operator-deliberate semantics (e.g. an authorised un-revoke).
  Use only when you understand exactly what you are doing; the
  bucket history retains both the revocation event and the
  unrevoke event so the audit trail is preserved either way, but
  consumers may see the unrevoked policy and act on it.

### Connection

- `--connect-url <nats-url>` (default `nats://127.0.0.1:4222`) —
  NATS connect URL for the capability-policy bucket.

---

## Receipt (stdout, on success)

JSON object, canonical (sort_keys=True, separators=(",",":")):

```json
{
  "cmd": "revoke",
  "mode": "cas",
  "key": "capability-policies/wirelang-eng/default",
  "registered_by": "wirelang-eng",
  "policy_id": "default",
  "revoked_at": "2026-05-11T22:00:00Z",
  "revocation_reason": "key compromise reported by audit",
  "expected_revision": 1,
  "previous_revision": 1,
  "new_revision": 2,
  "registered_at": "2026-05-11T22:15:00Z",
  "registered_by_publisher": "incident-responder-1"
}
```

Field semantics:

- `cmd` — always `"revoke"`. Pipelines can switch on this field.
- `mode` — `"cas"` (default + `--expected-revision`) or `"lww"`.
- `key` — canonical KV key.
- `registered_by` / `policy_id` — identity pair (echoed).
- `revoked_at` — applied revocation instant (RFC-3339, UTC, `Z` suffix).
- `revocation_reason` — echoed (or `null`).
- `expected_revision` — the revision the write was CAS-pinned to;
  `null` on the `--lww` path.
- `previous_revision` — the live revision the CLI READ before the
  write. Always present (also on `--lww`).
- `new_revision` — the revision the bucket assigned after the write.
- `registered_at` — the new `registered_at` set on the rewritten
  record (RFC-3339, UTC).
- `registered_by_publisher` — echoed (audit).

---

## Error envelopes (stderr) and exit codes

JSON object on stderr; non-zero exit code:

```json
{"error":"REVOCATION_CONFLICT","exit_code":8,"message":"..."}
```

| Exit code | Symbol                       | When it surfaces                                                                                     |
|-----------|------------------------------|------------------------------------------------------------------------------------------------------|
| 0         | `OK`                         | Revoke applied; receipt on stdout.                                                                   |
| 2         | `USAGE_ERROR`                | argparse rejected the flags (e.g. `--expected-revision` AND `--lww` supplied together).             |
| 3         | `INPUT_ERROR`                | Naive `--revoked-at`, empty `--registered-by-publisher`, malformed identity pair, etc.              |
| 4         | `VALIDATION_ERROR`           | Live envelope on the bucket is poisoned, or the rewritten record fails policy/record validation.    |
| 5         | `CAS_CONFLICT`               | `--expected-revision` does not match the live revision (a concurrent writer landed first).          |
| 6         | `BACKEND_ERROR`              | Other backend transport / I/O failure.                                                              |
| 8         | `REVOCATION_CONFLICT`        | Sprint-6 Tag-1 revocation-monotonic invariant tripped: un-revoke or advance-instant via CAS-pin.    |
| 9         | `REVOKE_TARGET_NOT_FOUND`    | The `(registered_by, policy_id)` record does not exist on the bucket.                               |

`REVOCATION_CONFLICT` is distinct from `CAS_CONFLICT`:
`CAS_CONFLICT` means "the revision drifted, re-read and retry";
`REVOCATION_CONFLICT` means "your write would violate the
revocation-monotonic invariant — mint a new `policy_id` instead, or
use `--lww` if you have explicit authority to unrevoke".

---

## Examples

### Apply an initial revocation (CAS auto-pin, safest)

```sh
wakir-schema-registry revoke \
  --registered-by wirelang-eng \
  --policy-id default \
  --revoked-at 2026-05-11T22:00:00Z \
  --revocation-reason "key compromise reported by audit ticket SEC-991" \
  --registered-by-publisher incident-responder-1
```

### Refresh the revocation reason (idempotent rewrite)

The same `--revoked-at` instant + a different `--revocation-reason`
is permitted by the Sprint-6 Tag-1 idempotent-rewrite invariant.
Useful for audit-trail enrichment after the initial revocation:

```sh
wakir-schema-registry revoke \
  --registered-by wirelang-eng \
  --policy-id default \
  --revoked-at 2026-05-11T22:00:00Z \
  --revocation-reason "audit-trail refresh: incident closed, ticket CR-42" \
  --registered-by-publisher audit-eng-1
```

### Explicit-revision CAS-pin (pipeline path)

When a pipeline has just observed a revision and wants to fail loud
on drift:

```sh
LIVE_REV=$(read-policy-revision wirelang-eng default)
wakir-schema-registry revoke \
  --registered-by wirelang-eng \
  --policy-id default \
  --revoked-at 2026-05-11T22:00:00Z \
  --revocation-reason "automated rotation: scheduled key retirement" \
  --registered-by-publisher key-rotation-cron \
  --expected-revision "$LIVE_REV"
```

A `CAS_CONFLICT` (5) here means a concurrent operator landed a
write between the read and the revoke; re-read and retry.

### LWW escape-hatch (operator-deliberate un-revoke)

**Use only with explicit authority.** Bypasses the
revocation-monotonic invariant. The bucket history retains the
revocation event so the audit trail is preserved:

```sh
wakir-schema-registry revoke \
  --registered-by wirelang-eng \
  --policy-id default \
  --revoked-at 1970-01-01T00:00:00Z \
  --revocation-reason "manual override: incident SEC-991 closed, see ADR-09XX" \
  --registered-by-publisher security-board-chair \
  --lww
```

(Note: the literal "no revocation" record cannot be expressed via
this CLI because `--revoked-at` is required; an operator-deliberate
"truly unrevoked" record requires the `put_with_revision` API
directly with `revoked_at=None`, or a tooling that writes the full
record envelope. Mint a new `policy_id` is almost always the right
move instead.)

---

## Hermetic test path

Tests inject a capability-bucket connect-factory via the public
`capability_bucket_factory` argument of `run()`:

```python
from wirelang.schemas.publisher_cli import run, ExitCode

def my_factory(connect_url):
    async def _connect(_url):
        backend = MyMockBackend()
        async def _cleanup(): pass
        return backend, _cleanup
    return _connect

code = run(
    ["revoke", "--registered-by", "...", ...],
    capability_bucket_factory=my_factory,
)
```

See `wirelang/tests/test_publisher_cli_revoke.py` for the full
in-memory mock pattern (CAS-aware KV mock mirroring nats-py shape).

---

## Implementation cross-references

- `wirelang/schemas/publisher_cli.py` — `_run_revoke`,
  `_add_revoke_flags`, `RevokeReceipt`, `ExitCode.REVOCATION_CONFLICT`,
  `ExitCode.REVOKE_TARGET_NOT_FOUND`.
- `wirelang/schemas/capability_policy_nats_kv_backend.py` — Sprint-6
  Tag-1 backend axis: `CapabilityPolicyRevocationConflict`,
  `put_with_revision` Gate 3 (revocation-monotonic).
- `wirelang/schemas/registered_by_capability.py` — Sprint-4 Tag-6 +
  Sprint-6 Tag-1: `DecisionSource.POLICY_REVOKED`, gate
  precedence ordering.
- `wirelang/tests/test_capability_policy_revocation.py` — Sprint-6
  Tag-1 backend tests (the foundation this CLI builds on).
- `wirelang/tests/test_publisher_cli_revoke.py` — Sprint-6 Tag-2
  CLI tests (this subcommand).

---

*Sprint-6 Tag-2 — Reza Tehrani (dev-engineering-2 / wirelang). Spec
v0.16.0 capability-policy-revocation operator surface.*
