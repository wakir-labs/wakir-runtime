# Sprint-6 Wirelang-Side Closeout

**Date:** 2026-05-12
**Owner:** Reza Tehrani (Wirelang-Identity-Owner)
**Scope:** Phase-2 Sprint-6 Tag-1..Tag-9, with Tag-10 Closeout-Preparation
**Spec lineage:** `schema-registry-spec.md` v0.15.0 → v0.22.0 (7 minor + 2 patch versions over 9 day-boxes)

This document is the in-repo summary of the Wirelang-side Sprint-6
achievements. The full Mira-hand ratification sketch lives in
`agents-workspaces/reza/outbox/2026-05-12-sprint-6-wirelang-side-closeout-skizze.md`
and is mirrored here for repo-readers who do not have workspace access.

## Achievements (10 substantial items over 9 day-boxes)

1. **Tag-1 (`e944b93`)** — Capability-Policy explicit revocation as
   monotonic-authority gesture on `registered_by_capability` surface.
   Spec v0.15.0 → v0.16.0. +12 tests (842 → 854).
2. **Tag-2 (`3516466`)** — Publisher-CLI `revoke` subcommand composing
   the Tag-1 backend axis onto operator surface, with CAS-pin auto-pin
   default, `--lww` escape hatch, RevokeReceipt audit pair.
   Spec v0.16.0 → v0.17.0. +14 tests (854 → 868).
3. **Tag-3 (`39ae824`)** — Watch-stream consumer-side
   `RevocationEventClassifier` with five-member `RevocationEventKind`
   enum and 10-branch decision table. Spec v0.17.0 → v0.18.0.
   +17 tests (868 → 885). **Bonus:** Z-A cross-review ack with four
   slot refinements.
4. **Tag-4 (`ece8f45`)** — SPIFFE-ID-binding spec on
   `identity-substrate.md` §5 with adapter-stub interface contract.
   Spec v0.18.0 → v0.18.1 (patch — spec-anchor).
5. **Tag-5 (`9c94517`)** — `MockSpiffeWorkloadApiAdapter` as
   hermetic test-substrate for SPIFFE-ID-binding. Spec
   v0.18.1 → v0.18.2. +14 tests.
6. **Tag-6 (`4ed84b0`)** — Cross-bucket `CapabilityPolicyReplicator`
   as async source→target watch-stream consumer.
   Spec v0.18.2 → v0.19.0. +15 tests. Phase-3 slots flagged
   (bidirectional, multi-source fan-in, watch-resume-from-revision,
   CAS-quorum).
7. **Tag-7 (`8b118c4`)** — Publisher-CLI `unrevoke` subcommand as
   operator-deliberate rescission; `real_spiffe_workload_api.py` stub
   as Phase-2c substrate slot; ADR-0052 promotion sketch.
   Spec v0.19.0 → v0.20.0. +10 tests.
8. **Tag-8 (`184d763`)** — ADR-0052 Class-P promotion `caveat_hash`
   v0.2.0 → v0.2.1 with algorithm-self-reference-exclusion contract
   as load-bearing invariant. Spec v0.20.0 → v0.21.0. +11 tests
   (T-CHP-07..11 regex-based both lanes; T-V0.2.1-01..05
   jsonschema-gated prod only; round-trip extension).
9. **Tag-9 (`6984ddb`)** — `RevocationEventKind.EXPLICIT_UNREVOKE`
   classifier-extension with `UnrevokeAuditMarker` envelope sub-object
   on `CapabilityPolicyRecord` (operator-audit-axis). Constructor
   invariant rejects marker on still-revoked policy.
   Replication-composition free over Tag-6.
   Spec v0.21.0 → v0.22.0. +11 tests (935 → 946).
10. **Tag-3 bonus** — Z-A cross-review ack (Aisha-protocol-ready) with
    four slot refinements (PyPI naming, NATS-JWT refresh,
    identity-substrate doc §5, workload-api adapter interface naming).

## Test progression

| Day-box | Spec | `wirelang/tests/` passed | Delta |
|---|---|---|---|
| Sprint-5 Tag-5 baseline | v0.15.0 | 842 | — |
| Sprint-6 Tag-1 | v0.16.0 | 854 | +12 |
| Sprint-6 Tag-2 | v0.17.0 | 868 | +14 |
| Sprint-6 Tag-3 | v0.18.0 | 885 | +17 |
| Sprint-6 Tag-4 | v0.18.1 | 885 | 0 |
| Sprint-6 Tag-5 | v0.18.2 | 899 | +14 |
| Sprint-6 Tag-6 | v0.19.0 | 914 | +15 |
| Sprint-6 Tag-7 | v0.20.0 | 924 | +10 |
| Sprint-6 Tag-8 | v0.21.0 | 935 | +11 |
| Sprint-6 Tag-9 | v0.22.0 | 946 | +11 |
| **Net Sprint-6** | **7 minor + 2 patch** | **854 → 946** | **+92 net** |

Test progression is monotonically additive across all 9 day-boxes.
Pre-existing date-dependent failures in
`tests/wat/test_aggregator_prev_hour_root.py` (Tomás domain) are
baseline-stable across the span — no Sprint-6 regression.

## Cross-review zones (orthogonal preserved)

- **Z-1 (Identity-Substrate)** — Tag-4 SPIFFE-ID-binding spec-anchor
  delivered; real adapter Phase-2c.
- **Z-2 (WAT × Wirelang)** — Tag-8 TV-W-2 pin-stability byte-equal
  verified via T-CHP-07; Tomás-owner hook preserved.
- **Z-B (NATS-KV × Wirelang)** — Tag-6 cross-bucket replication;
  bucket configs byte-unchanged; replication surface additive.
- **Z-A (SPIFFE/SPIRE)** — Tag-3 bonus Z-A ack with four slot
  refinements delivered (Aisha-protocol-ready).
- **Z-M (TV-W manifest, QA)** — Tag-8 TV-W-2 pin-pack-hash byte-stable;
  T-CHP-07 ratifies.

No cross-review marker uncovered a conflict in Sprint-6.

## Open items for Sprint-7 / Phase-3

**High (Sprint-7 Pfad-B substrate):**
- Multi-org-federation substrate (Tag-10 Item 2 — separate document).
- SPIFFE cross-trust-domain bridge (builds on Tag-4 spec-anchor + Tag-5 mock-adapter).

**Medium (Phase-2c / Sprint-7):**
- Production-side `wirelang/canonical/self_reference.py` module
  (~50 LOC) when a runtime token evaluator consumes the
  `caveat_hash` predicate (Tag-8 open item).
- Phase-2c `RealSpiffeWorkloadApiAdapter` functional impl (paired
  Kai SPIRE-live; operator hand).
- V-904 PoC preparation (Sprint-7 item).

**Low (Phase-3 / later sprints):**
- `persona_pin` Class-P promotion (residual; separate ADR).
- Phase-3 bidirectional replication.
- Multi-source fan-in.
- Watch-stream resume-from-revision.
- CAS-quorum capability-policy distribution.
- Watch-stream resume seed for marker map.
- Full Biscuit v3 binary-token revocation / unrevoke-list interpretation.

## Sprint-6 → Sprint-7 bridge

Sprint-6 established the **operationally-mature capability-policy
revocation axis**: backend persistence (Tag-1), operator CLI (Tag-2,
Tag-7 unrevoke), watch-stream consumer classification (Tag-3, Tag-9
EXPLICIT_UNREVOKE), cross-bucket replication (Tag-6), and
vocabulary-versioning promotion mechanic (Tag-8 ADR-0052 pattern).

Sprint-7 Pfad-B builds on this matured revocation axis by opening the
**federation substrate axis** as the next operationally-mature surface.
Tag-9 replication-composition-free-over-Tag-6 demonstrates that the
mid-sprint surfaces compose cleanly — Sprint-7 builds on top without
re-design.

See `agents-workspaces/reza/outbox/2026-05-12-sprint-7-pfad-b-multi-org-federation-skizze.md`
for the Sprint-7 Pfad-B substrate sketch.
