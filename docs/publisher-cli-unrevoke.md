# `wakir-schema-registry unrevoke` — Operator Manpage

**Module:** `wirelang.schemas.publisher_cli`
**Subcommand:** `unrevoke`
**Sprint:** Phase-2 Sprint-6 Tag-7 (additive over Sprint-6 Tag-2
`revoke` subcommand and Sprint-6 Tag-1 revocation backend axis)
**Bucket touched:** `wakir-capability-policies` (NOT `wakir-schemas`)

---

## Synopsis

```
wakir-schema-registry unrevoke
  --registered-by <issuer>
  --policy-id <policy-id>
  --registered-by-publisher <operator-id>
  [--unrevoke-reason <free-form>]
  [--registered-at <rfc3339-with-tz>]
  [--connect-url <nats-url>]
```

Note the deliberate absence of `--lww` and `--expected-revision`:
the unrevoke path is structurally LWW-only by design (see
"Why LWW only" below). The flag surface is intentionally narrow.

---

## Purpose

Apply an **operator-deliberate unrevoke** to a previously revoked
capability-policy record on the `wakir-capability-policies`
NATS-KV bucket. The unrevoke gesture writes a fully-formed record
with `revoked_at=None` and `revocation_reason=None`, semantically
restoring the policy to its pre-revoke state.

The subcommand is a **separate deliberate authority gesture**,
NOT an "undo" of a prior revoke. The audit trail therefore
explicitly separates `cmd="revoke"` receipts from `cmd="unrevoke"`
receipts so a downstream auditor can distinguish:

- "this policy was revoked and the revocation is still in effect"
- from "this policy was revoked, then deliberately unrevoked by
  an authorised operator at instant T"

The subcommand operates on a single record identified by the
`(registered_by, policy_id)` pair, on the SAME bucket as `revoke`.
It does NOT touch the `wakir-schemas` schema-registry bucket.

---

## Why LWW only

The Sprint-6 Tag-1 backend revocation-monotonic invariant on the
CAS-pin path (`NatsKvCapabilityPolicyBackend.put_with_revision`)
refuses any write that:

1. Sets `revoked_at=None` against a live revoked record (apparent
   un-revoke), or
2. Sets `revoked_at` to an instant != the live `revoked_at` (apparent
   advance-instant).

Both raise `CapabilityPolicyRevocationConflict`. The LWW path
(`NatsKvCapabilityPolicyBackend.put`) does NOT enforce the
invariant — by Sprint-6 Tag-1 design, the LWW path is the
operator-deliberate escape-hatch.

The unrevoke gesture is therefore by construction an LWW write.
Making this implicit in the subcommand (no `--lww` flag, no
`--expected-revision` flag) keeps the operator contract crisp:
**"there is exactly one way to unrevoke"**. Operators who need a
deliberate revoke via LWW continue to use `revoke --lww`; operators
who need a deliberate unrevoke use `unrevoke`. The two flag surfaces
are intentionally non-overlapping.

---

## Flags

### Identity pair (required)

- `--registered-by <issuer>` — `registered_by` of the
  capability-policy record. Same character class as the
  schema-registry `registered_by` convention.
- `--policy-id <policy-id>` — operator-supplied policy identifier,
  same character class as `registered_by`.

Together they derive the canonical KV key
`capability-policies/<registered_by>/<policy_id>`.

### Audit fields (required + optional)

- `--registered-by-publisher <operator-id>` (required) — the
  operator authoring the unrevoke. NOT the same as
  `--registered-by` (which names the policy issuer being
  unrevoked). Recorded on the rewritten record's
  `registered_by_publisher` field for audit purposes. Empty or
  whitespace-only strings are rejected with `INPUT_ERROR` (3).
- `--unrevoke-reason <free-form>` (optional but strongly
  recommended) — free-form audit string. Surfaced on the
  receipt's `unrevoke_reason` field. **NOT persisted on the
  rewritten record** — the rewritten record is byte-equal to a
  fresh unrevoked policy modulo `registered_at` and
  `registered_by_publisher` bookkeeping. Downstream pipelines that
  need the reason MUST capture the receipt JSON and store it
  alongside the bucket history (e.g. as a side-table or a comment
  on the incident-tracking ticket).
- `--registered-at <rfc3339-with-tz>` (optional) — overrides the
  rewritten record's `registered_at` timestamp. Defaults to the
  current UTC instant. Test paths and deterministic CI pipelines
  should supply this explicitly so receipts are byte-stable.

### Connection

- `--connect-url <nats-url>` (default `nats://127.0.0.1:4222`) —
  the NATS connect URL for the `wakir-capability-policies` bucket.

---

## Exit codes

| Code | Name                           | Meaning |
|------|--------------------------------|---------|
| 0    | `OK`                           | Unrevoke applied; receipt printed on stdout. |
| 2    | `USAGE_ERROR`                  | argparse-level rejection (missing flag, unknown flag, type mismatch, e.g. supplying `--lww` or `--expected-revision`). |
| 3    | `INPUT_ERROR`                  | Empty `--registered-by-publisher`, malformed `--registered-at`, invalid identity-pair characters. Pre-connect refusal. |
| 4    | `VALIDATION_ERROR`             | Live envelope is poisoned, or the rewritten record fails schema validation. |
| 5    | `CAS_CONFLICT`                 | Reserved (the unrevoke path uses LWW; this code is not raised in practice but is retained on the matrix for shared error-routing infrastructure). |
| 6    | `BACKEND_ERROR`                | Transport / backend error (NATS unavailable, unexpected exception during put). |
| 9    | `REVOKE_TARGET_NOT_FOUND`      | Target `(registered_by, policy_id)` does not exist on the bucket (reused from `revoke`; the "not found" semantics are identical). |
| 10   | `UNREVOKE_TARGET_NOT_REVOKED`  | Target exists on the bucket but is NOT currently revoked. Distinct from `REVOKE_TARGET_NOT_FOUND` so pipelines can disambiguate "policy never existed" from "policy exists but is already unrevoked". |

Note that `ExitCode.REVOCATION_CONFLICT` (8) is structurally
unreachable from the unrevoke path: the unrevoke uses LWW, which
does not enforce revocation-monotonic.

---

## Receipt shape (`UnrevokeReceipt`)

Twelve canonical fields, JSON-serialised with sorted keys + compact
separators (one line on stdout):

| Field                          | Type         | Meaning |
|--------------------------------|--------------|---------|
| `cmd`                          | string       | Always `"unrevoke"`. Pipelines switch on this to distinguish receipt shape from `RevokeReceipt`. |
| `mode`                         | string       | Always `"lww"`. Recorded explicitly so receipts from `revoke` and `unrevoke` have a parallel shape on the `mode` axis. |
| `key`                          | string       | Canonical KV key `capability-policies/<registered_by>/<policy_id>`. |
| `registered_by`                | string       | The policy issuer being unrevoked. |
| `policy_id`                    | string       | The policy identifier. |
| `previous_revoked_at`          | RFC-3339 str | The live record's `revoked_at` BEFORE the unrevoke. Always present (the unrevoke path refuses unrevoked targets). |
| `previous_revocation_reason`   | string\|null | The live record's `revocation_reason` BEFORE the unrevoke. `null` if the original revoke carried no reason. |
| `previous_revision`            | int          | The bucket revision that the CLI read BEFORE the unrevoke write. |
| `new_revision`                 | int          | The bucket revision assigned AFTER the unrevoke write succeeded. Always `previous_revision + 1` on a quiescent bucket. |
| `registered_at`                | RFC-3339 str | The new `registered_at` set on the rewritten record. |
| `registered_by_publisher`      | string       | The operator who authored the unrevoke. |
| `unrevoke_reason`              | string\|null | Operator-supplied audit string. **Receipt-only; not persisted.** |

The `previous_revoked_at` + `previous_revocation_reason` fields
together capture the prior revocation state for the audit trail;
a downstream tool can reconcile a `revoke` receipt and a later
`unrevoke` receipt by comparing `revoke.revoked_at` against
`unrevoke.previous_revoked_at` (these MUST be byte-equal under a
clean revoke → unrevoke round-trip).

---

## Worked examples

### 1. Happy path

Operator unrevokes a previously revoked policy:

```
wakir-schema-registry unrevoke \
  --registered-by wirelang-eng \
  --policy-id default \
  --registered-by-publisher incident-responder-2 \
  --unrevoke-reason "ticket-12345: post-incident review concluded; revocation rescinded" \
  --registered-at 2026-05-12T10:00:00Z
```

Stdout receipt:

```json
{"cmd":"unrevoke","key":"capability-policies/wirelang-eng/default","mode":"lww","new_revision":3,"policy_id":"default","previous_revocation_reason":"key compromise reported by audit","previous_revision":2,"previous_revoked_at":"2026-05-11T22:00:00Z","registered_at":"2026-05-12T10:00:00Z","registered_by":"wirelang-eng","registered_by_publisher":"incident-responder-2","unrevoke_reason":"ticket-12345: post-incident review concluded; revocation rescinded"}
```

Exit code: 0.

### 2. Target not revoked (exit 10)

Operator tries to unrevoke a policy that is not currently revoked:

```
wakir-schema-registry unrevoke \
  --registered-by wirelang-eng \
  --policy-id default \
  --registered-by-publisher incident-responder-2
```

Stderr:

```json
{"error":"UNREVOKE_TARGET_NOT_REVOKED","exit_code":10,"message":"capability-policy record is not currently revoked: registered_by='wirelang-eng' policy_id='default' (key='capability-policies/wirelang-eng/default'); unrevoke is a no-op surface against an unrevoked policy and is refused so the audit trail stays crisp"}
```

Exit code: 10. Bucket state is byte-equal-unchanged.

### 3. Target not found (exit 9)

Operator typos the `--policy-id`:

```
wakir-schema-registry unrevoke \
  --registered-by wirelang-eng \
  --policy-id deafult \
  --registered-by-publisher incident-responder-2
```

Stderr:

```json
{"error":"REVOKE_TARGET_NOT_FOUND","exit_code":9,"message":"capability-policy record not found: registered_by='wirelang-eng' policy_id='deafult' (key='capability-policies/wirelang-eng/deafult')"}
```

Exit code: 9 (reused from the `revoke` path; the "not found"
semantics are identical for both subcommands).

### 4. Round-trip audit-trail correlation

Pseudocode for a downstream pipeline reconciling a revoke receipt
with a subsequent unrevoke receipt:

```python
import json

with open("revoke-receipt.json") as f:
    revoke = json.load(f)
with open("unrevoke-receipt.json") as f:
    unrevoke = json.load(f)

assert revoke["cmd"] == "revoke"
assert unrevoke["cmd"] == "unrevoke"
assert revoke["registered_by"] == unrevoke["registered_by"]
assert revoke["policy_id"] == unrevoke["policy_id"]
assert revoke["revoked_at"] == unrevoke["previous_revoked_at"]
assert revoke["revocation_reason"] == unrevoke["previous_revocation_reason"]
assert unrevoke["previous_revision"] >= revoke["new_revision"]
```

A clean revoke → unrevoke round-trip with no intervening
non-monotonic-related writes will have
`unrevoke["previous_revision"] == revoke["new_revision"]`. If
other (non-revocation-related) writes happened between the two,
`unrevoke["previous_revision"]` will be `> revoke["new_revision"]`
but the byte-equality of `revoked_at` / `revocation_reason` / etc.
still holds.

---

## Operational notes

### Bundle preservation

The rewritten unrevoked record preserves every non-revocation
capability-bundle field byte-equally: `allowed_kids`,
`allowed_triples`, `disabled`, `note`, `not_before`, `not_after`
are all carried forward from the live revoked record. The
unrevoke gesture is therefore a **narrow surgical write** that
modifies only the revocation axis (`revoked_at` /
`revocation_reason`). An operator cannot accidentally lose
bundle state by unrevoking.

### Audit-consumer side observation

The Sprint-6 Tag-3 consumer-side revocation-event-filter
(`RevocationEventClassifier`) observes the unrevoke LWW write as a
PUT event with `event.record.policy.revoked_at == None` against a
prior-revoked classifier state. The classifier currently classifies
this as `REVOCATION_MONOTONIC_BREACH` because the LWW envelope
alone does NOT carry an operator marker distinguishing
"deliberate unrevoke via the Tag-7 CLI" from "accidental
non-monotonic write via some other path".

This is acceptable behaviour for Phase-2 because:

1. The operator gesture is observable through the receipt JSON
   (captured by the operator's CI / audit pipeline).
2. The bucket history (`history=5` per Z-B paired-update) retains
   the pre-unrevoke envelope so an audit consumer can reconstruct
   the transition byte-precisely.
3. Operator-driven LWW writes against a revoked policy are
   intrinsically rare; alerting on every `REVOCATION_MONOTONIC_BREACH`
   and reconciling with the operator's audit pipeline is the
   intended Phase-2 workflow.

A Phase-3 enhancement could add an `EXPLICIT_UNREVOKE` kind to
`RevocationEventKind` and a corresponding envelope marker
(e.g. `unrevoke_audit_marker: "tag-7"`) so the classifier can
distinguish the two cases in-band. This is listed as a Phase-3
wirelang-roadmap slot in the schema-registry-spec change-log entry
for v0.20.0.

### Cross-bucket replication

The Sprint-6 Tag-6 `CapabilityPolicyReplicator` carries unrevoked
records byte-precisely via the same `_record_to_envelope` codec.
An unrevoke on the source bucket therefore replicates to the
target as a PUT event with `revoked_at=None` (the same shape as a
fresh unrevoked policy). Under `SOURCE_WINS` conflict policy the
target's LWW path applies the write; under `CAS_PIN` the target's
Sprint-6 Tag-1 backend gate refuses the write and the replicator
advances `revocation_breaches` (the operator MUST then run
`unrevoke` against the target bucket independently — replication
does not propagate operator authority).

### Concurrency caveat

The unrevoke path does NOT use CAS-pin. If another operator (or
another instance of the same operator) writes to the same key
between the CLI's pre-write read and the LWW write, the CLI's
write will silently overwrite that intervening write. This is the
same caveat that applies to `revoke --lww`. Pipelines that require
strict ordering across concurrent operator writes SHOULD
serialise unrevoke operations through a single operator endpoint
or accept the LWW semantics.

---

## Cross-references

- Sprint-6 Tag-1 backend revocation-monotonic invariant:
  `wirelang/schemas/capability_policy_nats_kv_backend.py`
  (`put_with_revision`, `CapabilityPolicyRevocationConflict`).
- Sprint-6 Tag-2 `revoke` subcommand:
  `docs/publisher-cli-revoke.md`.
- Sprint-6 Tag-3 consumer-side revocation-event-filter:
  `docs/revocation-event-filter.md`.
- Sprint-6 Tag-6 cross-bucket replicator:
  `wirelang.schemas.capability_policy_replication`.
- Schema-registry spec (change-log entry for v0.20.0):
  `wirelang/specs/schema-registry-spec.md`.
- Test inventory: `wirelang/tests/test_publisher_cli_unrevoke.py`
  (T-SR-UREV-01..08).
