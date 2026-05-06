<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Callandor GmbH and contributors

Licensed under the Creative Commons Attribution 4.0 International
License. Full text: https://creativecommons.org/licenses/by/4.0/
-->

# Recovery-Drill Result → WAT Leaf Projection — Phase-1b Sketch

Version: `wakir-recovery-drill-leaf-projection/v1-draft`
Status: **draft**, Phase-1b. First production drill anchored Q3 2026.
Audience: identity-substrate operators running quarterly cold-storage
recovery drills (`wirelang.identity.recovery_drill`) and audit-trail
consumers verifying the three-year drill cadence.

This document specifies how a `RecoveryDrillResult`
(`wirelang/identity/recovery_drill.py`) projects onto the WAT four-
field leaf tuple, so each quarterly drill emits an audit-trail event
that an external auditor can verify three years later without trusting
the operator's logs.

## 1. Use case

Per ADR-0023b §3 (consensus marker D-2), the Wakir 2-of-3 cold-
storage pattern requires a **quarterly recovery drill**. The drill
simulates the loss of each share in turn and confirms that the
remaining quorum still reconstructs the master secret. A drill is
"successful" only if every one-loss case recovers and (when an
expected master is supplied) every recovery matches.

The auditor's question, three years later, is:

> Did the operator actually run a drill in Q2 2026, and did it pass?

Without an audit trail, the answer is "trust the operator's log".
With WAT-anchored drill events, the answer is "here is the OTS
receipt anchoring the four-tuple commitment for that drill, and here
is the Bitcoin block that confirms the timestamp predates the audit
question". This is the multi-year integrity property WAT is designed
to provide.

## 2. Projection rule

Given a `RecoveryDrillResult`, the projection produces:

```
event_id              = "recovery-drill-" + uuidv7()
time                  = drill_run_time   (RFC 3339, UTC, Z-suffix)
payload_hash          = SHA-256( JCS( RecoveryDrillResult-as-dict ) ), hex-lower
capability_token_hash = caprefs[0]  (first capability that authorised the drill)
                       OR empty string if the drill ran outside a
                       capability-token context (e.g. operator-local).
```

### 2.1 `event_id` rule

`event_id = "recovery-drill-" + UUIDv7`.

The `recovery-drill-` prefix is human-readable in audit queries and
is hash-stable (the prefix is fixed bytes). The UUIDv7 portion
preserves the time-ordered lexicographic-sort property documented in
the WAT leaf-projection spec (`wirelang/specs/wat-leaf-projection.md`
§3.1). The full string is the `event_id` field of the four-tuple —
not the UUID alone.

This is a correction relative to the early sketch that used
`event_id = uuidv7()` without the prefix: the prefix gives the
auditor a one-grep filter ("show me every recovery-drill leaf in the
2026 archive") without introducing a separate index. It remains
B1-conformant because `event_id` is opaque to the leaf-hash function.

### 2.2 `payload_hash` rule

The drill result is serialised to a dict with the following shape
before JCS canonicalisation:

```json
{
  "success":              <bool>,
  "attempts":             <int>,
  "threshold_met":        <bool>,
  "lost_share_index":     <int | null>,
  "recovered_master_hash":"<hex string of SHA-256(recovered_master), or null>",
  "per_round_outcomes": [
    {"lost_index": <int>, "recovered_ok": <bool>}, ...
  ]
}
```

Note the deliberate omission: `recovered_master` (the actual master
secret bytes) MUST NOT be projected into the audit-trail leaf. The
projection records the **hash** of the recovered master, so an
auditor can confirm the drill recovered the right master (by
comparing against an out-of-band reference hash) without leaking the
master itself onto a public timestamp chain.

The `per_round_outcomes` list is sorted by `lost_index` ascending
before serialisation; the projection enforces this so two drills
with the same outcomes always produce the same payload hash.

### 2.3 `capability_token_hash` rule

If the drill was authorised by a Wirelang capability token (e.g. an
HR-issued "quarterly-drill" token), the first such token's hash goes
into `capability_token_hash` per the v1 leaf-projection rule
(`wirelang/specs/wat-leaf-projection.md` §3.4).

If the drill ran outside any capability-token context (operator-
local invocation), `capability_token_hash` is the empty string.
Phase-1b operators SHOULD wire drills through a capability token so
the audit trail records the authorising delegation chain; the empty-
string fallback exists for Phase-1a and for emergency recovery
scenarios where no live capability infrastructure is reachable.

## 3. Cadence and anchor schedule

| step                            | when                                       |
| ------------------------------- | ------------------------------------------ |
| operator runs drill             | first business day of each quarter, UTC    |
| drill emits Wirelang frame      | within minutes of drill completion         |
| frame is hashed and spooled     | hour-spool covering `time` (§5)            |
| spool is sealed                 | hour-end + 5-minute late window            |
| WAT manifest built and OTS-anchored | hourly cron on the same day            |
| OTS calendar confirms           | minutes to hours later                     |
| Bitcoin block attestation       | days to weeks later (`ots upgrade` weekly) |

The three-year audit window opens once the Bitcoin attestation
finalises. Until then, a calendar-only attestation is still
verifiable but weaker.

## 4. Phase-1b status

This document is a draft. Open items before Phase-1b finalisation:

- **First production drill: Q3 2026.** A dry-run drill in Q2 2026
  validates the projection against the bridge implementation
  (Phase-1a-Tag-7+). Q3 2026 is the first cadence-bearing drill that
  is expected to anchor cleanly.
- **Capability-token issuer.** The HR module is the planned issuer of
  quarterly-drill tokens; the issuer DID and token shape are
  specified in `wirelang/specs/layer-3-capability-token.md` and
  cross-referenced here once the token format is final.
- **`recovered_master` redaction policy.** §2.2 commits to "hash, do
  not include". A future revision MAY allow operators to opt into
  including the master-hash *and* an encrypted-to-auditor blob of
  the master, but that is out of scope for v1-draft.

## 5. Reference implementation

- Drill simulator: `wirelang/identity/recovery_drill.py` (Apache-2.0).
- Hash core: `wat.merkle.aggregator.compute_leaf_hash` (BSL-1.1) —
  shared with all other WAT leaf projections.
- Related specs:
  - `wirelang/specs/wat-leaf-projection.md` — generic Layer-1 → leaf rule.
  - `docs/wat-hash-spec.md` — cross-domain JCS+SHA-256 contract.
  - `wirelang/specs/identity-substrate.md` — SLIP-39 split + recovery.
