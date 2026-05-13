# Sprint-7 Wirelang-Side Closeout

**Date:** 2026-05-12
**Owner:** Reza Tehrani (Wirelang-Identity-Owner)
**Scope:** Phase-2 Sprint-7 Tag-1..Tag-6, with Tag-7 Closeout-Preparation
**Spec lineage:** `schema-registry-spec.md` v0.22.0 → v0.28.0 (6 additive minor versions over 6 day-boxes)
**Parent:** Sprint-6 Wirelang Closeout tip `f4dd31e` (commit
`docs(wirelang): Sprint-6 Wirelang-side closeout (Phase-2 Sprint-6 Tag-10)`).

This document is the in-repo summary of the Wirelang-side Sprint-7
achievements. The full Mira-hand ratification sketch lives in
`agents-workspaces/reza/outbox/2026-05-13-sprint-7-wirelang-side-closeout-skizze.md`
and is mirrored here for repo-readers who do not have workspace access.

## Achievements (6 substantial items over 6 day-boxes)

1. **Tag-1 (`9aef092`)** — Multi-Org-Federation-Substrate
   (`MultiOrgAttestationEnvelope`) with Datalog vocabulary extensions
   `peer_org/1` and `federation_route/2` reserved per ADR-0031 D2.
   Bonus: A2A spec §4.x finding raised to Mira, ADR-0031 E1 freigabe
   for DID-Document emission ratified. Spec v0.22.0 → v0.23.0.
2. **Tag-2 (`4cb1c7e`)** — `MultiOrgAttestationNatsKvBackend`
   persistent NATS-KV backend for `wakir-multi-org-attestations`
   bucket. Authority-gesture monotonic-invariant gate as load-bearing
   Class-P promotion (ordering `isinstance → expected_revision →
   monotonic → CAS`). Surfaces: `put`, `put_with_revision`,
   `get_with_revision`, `delete`, `snapshot`, `open_watch_stream`,
   plus `bootstrap_multi_org_attestation_target_from_source` one-shot.
   Spec v0.23.0 → v0.24.0.
3. **Tag-3 (`0908d85`)** — `SpiffeCrossTrustDomainBridge` module for
   cross-trust-domain SPIFFE-ID resolution. `spiffe://<trust-domain>/
   <workload>` parser with `peer_org` caveat binding;
   trust-domain whitelist as operator surface (deny-by-default).
   `BRIDGE_RESOLUTION_SCHEMA=wakir.federation.spiffe-bridge/1` as
   first WAT-anchor surface for Zone-O D-1 audit federation annex.
   Spec v0.24.0 → v0.25.0.
4. **Tag-4 (`3e2ebbe`)** — `CapabilityAttenuationChainVerifier` as
   passive defence-in-depth layer on Tag-1 substrate + Tag-2 backend +
   Tag-3 bridge. Monotonic attenuation enforcement along delegation
   chains (subset relation per hop). Five-error hierarchy: shape,
   order, stale-replay, cross-org-boundary, revoked-link.
   `CHAIN_VERIFICATION_SCHEMA=wakir.federation.capability-attenuation-
   chain/1` as second WAT-anchor surface. Spec v0.25.0 → v0.26.0.
5. **Tag-5 (`d0669f9`)** — `UnrevokeAuditMarkerCrossOrgExporter` with
   pseudonymisation boundary: raw `unrevoke_reason` and
   `previous_revocation_reason` stripped, replaced by
   `unrevoke_reason_class` (categorical 5-value enum) and
   `previous_revocation_reason_hash` (BLAKE2b-256 route-keyed,
   personalisation `b"wakir-ump-1\x00\x00\x00\x00\x00"`).
   `marker_id` timing-invariant audit-leaf identifier excludes
   `exported_at`. `EXPORT_SCHEMA=wakir.federation.unrevoke-audit-
   marker-export/1` as third WAT-anchor surface. Spec v0.26.0 → v0.27.0.
6. **Tag-6 (`f60d1fa`)** — `MultiOrgAttestationReplicator` async
   orchestrator composing Tag-2 `bootstrap_multi_org_attestation_
   target_from_source` (one-shot initial sync) with continuous
   watch-stream live-tail loop. Together they form the full
   cross-bucket replication suite for `wakir-multi-org-attestations`,
   pattern-mirroring Sprint-6 Tag-6 capability-policy replicator.
   Conflict policies `SOURCE_WINS` (default, LWW) and `CAS_PIN`
   (revision-pin with create-if-absent fall-through). Halt policy:
   three operator-tunable flags defaulting to "continue and count"
   so a hostile source stream does not crash the replicator.
   Resume cursor `last_revision` advanced on apply AND filter-skip,
   never regresses on lower-revision replay. Spec v0.27.0 → v0.28.0.

## Metrics

- **Spec versions:** v0.22.0 → v0.28.0 (6 additive minor bumps,
  no breaking changes; all pre-existing frames remain valid against
  v0.28 verifiers).
- **Tests:** 962 → 1010 (+48 net, 1000-test threshold crossed during
  Sprint-7).
- **β-pushes:** 6 (autonomous via ADR-0049 worktree-pattern with
  `-runtime` suffix; worktree cleanup post-push).
- **Cross-Review-Zone-O acks:** 3/3 complete (Tomás D-1, Kai D-2,
  Júlia D-3).
- **ADR ratifications:** ADR-0031 E1 freigabe (DID-Document
  emission) ratified by Mira on 2026-05-12.
- **Naming corrections:** Zone-O renamed from initial Zone-D draft
  to avoid collision with Phala-Zone-D (TEE-Federation-Substrate
  from Sprint-5).

## Open items for Sprint-8+

### HIGH (4)

- **H-1:** WAT annex code-drop for Tomás-D-1 counter-items
  (cross-org audit anchor schemas downstream of the three Sprint-7
  WAT-anchor surfaces: BRIDGE_RESOLUTION_SCHEMA,
  CHAIN_VERIFICATION_SCHEMA, EXPORT_SCHEMA).
- **H-2:** Annex schema-design clarifications, Tomás × Reza pair.
- **H-3:** DevOps F-D2-1..4 (Kai-counter Sprint-7 topology items).
- **H-4:** Federation-topology operator surface (NATS multi-org
  cluster + SPIRE-Live coupling).

### MEDIUM (4)

- **M-1:** Phase-2c RealAdapter functional implementation
  (Reza, paired with Kai SPIRE-Live).
- **M-2:** Kai SPIRE-Live Phase-2.3+ operator-hand coupling.
- **M-3:** Live federation trial (Sprint-8+, gated on Mira-hand
  approval of external org-side).
- **M-4:** Multi-org-attestation filter refinements.

### LOW (5, Phase-3 backlog)

- **L-1:** Bidirectional replication via CRDT.
- **L-2:** Multi-source fan-in (N>2 source-org streams).
- **L-3:** Watch-stream resume-seed-from-marker.
- **L-4:** Biscuit-v3 token revocation (binary-token revoke).
- **L-5:** Watch-stream resume-cursor wire-up (`last_revision`
  from Tag-6 replicator threaded back into `open_watch_stream`
  start-cursor).

## Sprint-7 → Sprint-8 bridge

Multi-org-federation substrate is **hermetic ready**. All four
ADR-0031-S-1..S-4 axes have substantial substance:

- **S-1 (substrate carrier):** `MultiOrgAttestationEnvelope` +
  Datalog vocabulary extensions (Tag-1).
- **S-2 (bridge surface):** `SpiffeCrossTrustDomainBridge` (Tag-3).
- **S-3 (persistent backend):** `MultiOrgAttestationNatsKvBackend`
  (Tag-2).
- **S-4 (replication suite):** bootstrap (Tag-2) + live-tail (Tag-6)
  = full cross-bucket replication.

Plus cross-org export surface (Tag-5) for `UnrevokeAuditMarker` and
capability-attenuation-chain verifier (Tag-4) as trust-layer
defence-in-depth.

**Phase-3 Pfad-B (Live-Federation-Trial)** is gated on:

1. Mira-hand approval of external org-side (Mira-Approval-Gate M-3).
2. Tomás WAT annex code-drop (H-1 + H-2).
3. Kai DevOps federation-topology (H-3 + H-4).

Reza-Wirelang-side is **not blocked** on L-1..L-5 (Phase-3 backlog
items are additive Phase-3 extensions, not hard requirements for
the live-trial).

## Cross-sprint linkage Sprint-6 ↔ Sprint-7

Sprint-7 builds **strictly additively** on Sprint-6 closeout
substrate:

| Sprint-6 output                                            | Sprint-7 consumer                             |
|------------------------------------------------------------|-----------------------------------------------|
| Tag-1 capability-policy revocation                         | Tag-4 attenuation chain (caveat stack)        |
| Tag-6 capability-policy cross-bucket replicator            | Tag-6 pattern-mirror                          |
| Tag-9 EXPLICIT_UNREVOKE classifier                         | Tag-5 cross-org export surface                |
| Tag-7 SPIFFE real-stub                                     | Tag-3 SPIFFE cross-trust-domain bridge        |
| Tag-8 ADR-0052 Class-P promotion `caveat_hash`             | Tag-2 authority-gesture monotonic gate        |

No Sprint-6 output is byte-broken in Sprint-7. All consumer surfaces
respect the Sprint-6 closeout-stabilised interfaces.

---

Doku-only commit; no test drift. Sprint-7 closeout stamp delivered
separately as Mira-hand ratification sketch at
`agents-workspaces/reza/outbox/2026-05-13-sprint-7-wirelang-side-
closeout-skizze.md`.
