<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# WAT Manifest v2 — Multi-Cap Trigger (Stub Spec)

Status: **stub / draft**, Phase-1b Sprint-2 prep
Owner: dev-engineering / matrix-lead
Origin: Tag-22 closeout-hygiene Item 4 (deferred), Tag-23 followup
Bezug: WAT-Phase-1a-Spec §3.4.1 multi-cap-ordering, ADR-0009 §3
acceptance, wirelang-engineering Cross-Review Zone 2 (capability-token × wat-leaf
sync).

This stub is **not** an implementation directive. It is the Sprint-2
trigger surface so wirelang-engineering, frontend-engineering and pengine-engineering can review the proposed v2
manifest shape before code lands.

---

## 1. Problem statement

The Layer-1 audit-event schema (`docs/wat-spool-spec.md`) allows a
frame's `caprefs[]` to carry **one or more** capability-token hash
references. Manifest-v1 (current production) projects multi-cap
frames onto a single `capability_token_hash` field by taking
`caprefs[0]` (`wat/ingestion/wirelang_bridge.py:extract_capability_token_hash`,
WAT-Phase-1a-Spec §3.4.1).

That projection is **lossy** for the audit trail when a frame
genuinely carries multiple capabilities. The spec acknowledges this
and recommends "one frame per capability" as the v1 producer
workaround — fine for simple producers, awkward for batched-call
agents that delegate across multiple capabilities in a single frame.

Manifest-v2 closes the gap by keeping `caprefs[0]` as the canonical
audit anchor (backwards-compatible) **and** exposing the full
`caprefs[]` set in a manifest sidecar that the verifier and audit
query layer can both reach.

## 2. Trigger condition

A v2 manifest MUST be emitted **iff** at least one ingested frame in
the hour has `len(caprefs) > 1`. Hours where every frame has zero
or one capref continue to emit v1 manifests verbatim — no behavioural
change for the common case.

This means a hour-manifest's `version` field becomes a discriminator:

```
"version": "wat-manifest/1.0"   # all frames have ≤ 1 capref (current)
"version": "wat-manifest/2.0"   # at least one frame has > 1 caprefs
```

Verifier and audit-query both fall back to v1 semantics on v1
manifests, and read the new sidecar block on v2.

## 3. v2 manifest schema delta

v2 manifests retain every v1 field unchanged. The delta is two
**additive** keys, side-by-side with `events`:

```json
{
  "version": "wat-manifest/2.0",
  "hour_slot": "...",
  "merkle_root": "...",
  "event_count": ...,
  "events": [...],
  "leaves": [...],
  "tree_levels": [...],
  "build_time": "...",

  "multi_cap_events": {
    "<event_id>": {
      "caprefs_full": [
        "sha256:<hex-1>",
        "sha256:<hex-2>",
        ...
      ],
      "caprefs_root": "<sha256-of-canonical-caprefs[]-merkle-root>"
    },
    ...
  },
  "multi_cap_summary": {
    "events_with_multi_cap": <int>,
    "max_caprefs_in_any_event": <int>,
    "distinct_capability_token_hashes_in_hour": <int>
  }
}
```

Design notes:

- **`caprefs_full`** is the verbatim ordered list as the producer
  emitted it. Audit queries that want "did agent X exercise capability
  Y in hour H?" can grep this set directly.
- **`caprefs_root`** is a sha256 over a canonical lexicographic
  Merkle of the `caprefs[]` set — gives a single hash the audit
  query can pin and the verifier can re-derive deterministically
  without iterating the full list. Open question: do we want
  ordered Merkle (preserves producer intent) or sorted Merkle (gives
  set-equality)? Spec §3.4.1 favours ordered semantics → I propose
  ordered Merkle. wirelang-engineering-Zone-2 review needed.
- **`multi_cap_summary`** is a pure roll-up the brand-page / ops
  dashboard can render without scanning the whole manifest.

## 4. Verifier behaviour

`wakir-verify <event_id>` for an event in a v2-manifest hour:

- Runs all v1 checks unchanged (leaf hash, inclusion proof, OTS
  receipt, Bitcoin attestation).
- **If** the event_id appears in `multi_cap_events`:
  - Re-derive `caprefs_root` over `caprefs_full` and verify it
    matches the manifest claim.
  - Print an additional line `multi_cap: <count> capabilities
    (root=<8 hex>...)` in human-mode output.
  - In `--output json` mode (Sprint-1 Tag-25 pickup): include
    `caprefs_full[]` and `caprefs_root` in the result object.
- **If not**: behaviour identical to v1.

`--chain-check` semantics unchanged. The multi-cap layer is purely
metadata, never affects the Bitcoin-anchor validation path.

Exit codes:

- `0` — verified (and chain-verified, multi-cap-root matches if
  applicable).
- `1` — failed (existing semantics + multi-cap-root mismatch is a
  new failure case).
- `3` — pending.
- `4` — chain-mismatch.

## 5. Aggregator behaviour (the actual code-touchpoint for Sprint-2)

`wat/aggregator.py` (or wherever the v1 manifest gets built today —
TBD pending file walk in Sprint-2 Tag-1) gets a new branch:

```python
def build_manifest(events, hour_slot, ...):
    multi_cap_events = {
        evt.event_id: {
            "caprefs_full": evt.caprefs,
            "caprefs_root": _caprefs_merkle_root(evt.caprefs),
        }
        for evt in events
        if len(evt.caprefs) > 1
    }
    if not multi_cap_events:
        return _build_v1(events, hour_slot, ...)
    v1 = _build_v1(events, hour_slot, ...)
    v1["version"] = "wat-manifest/2.0"
    v1["multi_cap_events"] = multi_cap_events
    v1["multi_cap_summary"] = _summary(events, multi_cap_events)
    return v1
```

This keeps the v1 build path the canonical default and adds v2 only
when triggered. No regression risk for the common case.

## 6. Test plan (Sprint-2)

- `test_manifest_v2_trigger`: frames with `caprefs=[]` and
  `caprefs=["sha256:aaa..."]` only → v1 manifest emitted, no
  `multi_cap_*` keys.
- `test_manifest_v2_emitted`: at least one frame with `caprefs=[a, b]`
  → v2 manifest, `multi_cap_events[evt_id]` populated, summary
  correct.
- `test_caprefs_root_deterministic`: same `caprefs[]` ordered list
  → same root across runs (hash-stability).
- `test_caprefs_root_order_sensitive`: `[a, b]` vs `[b, a]` →
  different roots (preserves producer intent, per §3.4.1
  ordered-semantics decision pending wirelang-engineering review).
- `test_verifier_v2_validates_caprefs_root`: tamper with
  `caprefs_full` → verifier exits 1 with multi-cap-root mismatch.
- `test_verifier_v1_unchanged`: existing v1 manifests still verify
  with all current exit-code semantics.

## 7. Cross-Persona impact

| Persona  | Impact                                                                |
| -------- | --------------------------------------------------------------------- |
| wirelang-engineering     | **Zone 2 review needed** — confirm `caprefs_root` ordered-vs-sorted, confirm v2 schema fits Wirelang capability-token-projection spec. |
| container-engineering      | None — manifests stay event-payload, no NATS/Container-bridge effect. |
| frontend-engineering     | Frontend: `--output json` schema (Tag-25 pickup) gains optional       |
|          | `multi_cap` block. Brand-page-embed unaffected for v1-only hours.     |
| sre-engineering      | None — SRE pipeline indifferent to manifest version.                  |
| pengine-engineering    | **Maybe** — PEngine V-907 cache-pointer may want to opt into          |
|          | `caprefs_full` for replay; needs pengine-engineering-PEngine-Bridge review.         |
| qa-engineering    | QA test-vector additions (TV-x for multi-cap hour).                   |

## 8. Open questions (must resolve before Sprint-2 implementation)

1. Ordered vs. sorted `caprefs_root` Merkle? **Proposal: ordered**.
   wirelang-engineering-Zone-2 sign-off needed.
2. Emit empty `multi_cap_events: {}` on v2-but-no-multi-cap-frames-
   actually-occurred (i.e., all frames have ≤1 capref but somebody
   forced v2)? **Proposal: never. Trigger condition is strict** —
   you only see v2 if at least one frame actually has >1 caprefs.
3. Backwards-compatible verifier strict-mode flag (`--manifest-version`
   override) for downgrade testing? **Proposal: defer to Sprint-3**
   unless an audit query test plan demands it earlier.
4. Test-vector for multi-cap hour: which is the canonical TV
   shorthand — TV-4? Discuss with qa-engineering at QA-handover.

## 9. Implementation timeline (proposed)

- **Sprint-1 Tag-25:** `--output json` for verifier (frontend-engineering pickup,
  Tag-23 inbox-memo) lands first. v1-only payload, but the JSON
  schema is forward-compatible with §4 multi-cap additions.
- **Sprint-2 Tag-1-3:** v2 manifest aggregator + tests (this stub
  becomes implementation directive after open-question resolution).
- **Sprint-2 Tag-4-5:** verifier v2-aware path + tests.
- **Sprint-2 Tag-6:** Cross-Review Zone 2 (wirelang-engineering), Zone E (frontend-engineering),
  Zone K (pengine-engineering) sign-off.
- **Sprint-2 Tag-7+:** Brand-demo-memo update with first multi-cap
  hour Bitcoin-anchored.

---

— dev-engineering / matrix-lead
