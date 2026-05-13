<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors

License: This document is licensed under the Creative Commons Attribution
4.0 International License. To view a copy, see
<https://creativecommons.org/licenses/by/4.0/>.
-->

---
spec: wirelang-schema-registry
version: 0.28.0
status: draft
date: 2026-05-13
audience: implementers, integrators, operators
license: CC-BY-4.0
---

# Wirelang Schema Registry — NATS-KV Backend Specification (v0.28.0)

**Sprint-8 Tag-1 anchor (2026-05-13).** The change-log table below is the
v0.22.0 surface as of Sprint-6 Tag-9. Sprint-7 (Multi-Org-Federation-
Substrate, six additive achievements) ratified on 2026-05-13 lands a
batch of bumps to v0.28.0 which are tracked in the Sprint-7 closeout
artefact at `agents-workspaces/reza/outbox/2026-05-13-sprint-7-wirelang-side-closeout-skizze.md`
and will be folded into this change-log on the Sprint-8 Tag-N spec-
consolidation box (Reza-side cleanup item). The Sprint-8 Tag-1
RealAdapter-Mirror (`wirelang/adapters/real_nats_adapter/`) is
documented in `identity-substrate.md` §5.8 (paired with
`real_spiffe_workload_api.py` Sprint-6 Tag-7 Slot-2-Mirror); the
schema-registry-spec change-log entry for the RealAdapter-Mirror is
deferred to the same Sprint-8 Tag-N consolidation box (the adapter
is an implementation surface, not a schema-registry surface — no
bucket-shape change, no envelope-shape change).

**Change log**

| Version | Date       | Change                                                 |
|---------|------------|--------------------------------------------------------|
| 0.28.0  | 2026-05-12 | Phase-2 Sprint-7 Tag-6 lands the **Multi-Org-Attestation-Live-Tail-Replicator** as the continuous-stream composition layer on top of the Sprint-7 Tag-2 `bootstrap_multi_org_attestation_target_from_source` one-shot bootstrap. Together the two surfaces form the **full cross-bucket replication suite** for the `wakir-multi-org-attestations` bucket (pattern-mirror on the Sprint-6 Tag-6 capability-policy cross-bucket replicator at `wirelang/schemas/capability_policy_replication.py`). New module `wirelang.federation.multi_org_attestation_live_tail_replicator` (NEW, ~390 LOC incl. module docstring + ~480 test-LOC) ships: (1) `MultiOrgAttestationReplicator` async-orchestrator dataclass composing Tag-2 backend `snapshot` + `watch` + `put` / `put_with_revision` into a one-way (source → target) durable-stream replicator — `async run(*, bootstrap: bool = True) -> MultiOrgAttestationReplicationMetrics` is the primary entry-point; `async bootstrap()` delegates to the Tag-2 one-shot helper for the initial-sync phase; the live-tail loop opens `open_watch_stream(self.source)` and routes each decoded `MultiOrgAttestationWatchEvent` through filter → conflict-policy → target write/delete; (2) **Conflict policies (reused from Tag-2)** — `SOURCE_WINS` (LWW via `put`, default) and `CAS_PIN` (`put_with_revision` against `get_with_revision`-observed revision with create-if-absent fall-through to `put` for absent keys); under both policies the Tag-2 backend's authority-gesture monotonic-invariant gate runs in-band on every write (the gate ordering is `isinstance → expected_revision → monotonic → CAS`, so a stale-revision race cannot un-set an authority anchor); (3) **Halt policy** — three operator-tunable flags defaulting to "continue and count" so a noisy or hostile source stream does NOT crash the replicator: `halt_on_envelope_error` (default `True`, re-raise on first envelope poison), `halt_on_cas_conflict` (default `False`, CAS_PIN-only), `halt_on_monotonic_breach` (default `False`, both policies); (4) **Filter surface (reused from Tag-2)** — `MultiOrgAttestationReplicationFilter` Callable invoked on every observed event (bootstrap synthetic AND live tail); `APPLY` / `SKIP` decisions counted via `bootstrap_skipped_by_filter` and `events_skipped_by_filter` counters; (5) **Resume cursor** — additive `last_revision: int = 0` field on the replicator that monotonically tracks the highest revision observed on the live tail (apply AND filter-skip events advance it; never regresses on a lower-revision replay). The cursor is the **operator-side resume signal**: on crash-restart an operator persists the cursor and (in Phase-3) re-bakes it into a `watch(..., resume_from=...)` open call. Tag-6 itself does NOT wire the cursor back into the open call — that requires nats-py adapter support and is reserved for Phase-3 (mirror of the Sprint-6 Tag-6 capability-policy replicator's resume-policy reservation). The Tag-6 replicator's contract: `last_revision` reflects ONLY live-tail revisions (bootstrap-pass reads via `snapshot` + `list_keys` + `get_with_revision` surface per-record revisions but NOT a stream-level high-water-mark; resume from a partial bootstrap is structurally always a full re-bootstrap, which the bootstrap pass treats as idempotent). **Composition contract** — the replicator is a *thin composition*: no new backend surface, no new envelope shape, no schema-version bump on the per-record envelope (`wakir.federation.multi-org-attestation/1` byte-unchanged from Tag-2). The Tag-6 spec-bump (v0.27.0 → v0.28.0) reflects the new orchestration surface, not a new substrate. The full cross-bucket replication suite for the `wakir-multi-org-attestations` bucket now mirrors the Sprint-6 Tag-6 capability-policy suite axis-by-axis: bootstrap pass (Tag-2 = S6-Tag-6 helper) + live-tail loop (Tag-6 = S6-Tag-6 replicator class). **Failure-mode surfacing** — all three Tag-2 backend exception types pass through cleanly: `MultiOrgAttestationEnvelopeError` (envelope poison on the source watch-stream — `envelope_errors` counter), `MultiOrgAttestationCasConflict` (CAS-pin rejected — `cas_conflicts` counter, CAS_PIN policy only), `MultiOrgAttestationMonotonicConflict` (authority-anchor mutation refused — `monotonic_breaches` counter, both policies via in-band Tag-2 gate). Determinism contract: a bootstrap-only run (`run(bootstrap=True)` with an immediately-terminating watch-stream) is byte-equivalent to a direct call to `bootstrap_multi_org_attestation_target_from_source`; a live-tail-only run (`run(bootstrap=False)` on a pre-bootstrapped target) applies every observed event via the configured conflict policy with filtered-out events observed-and-counted-but-not-applied. Federation `__init__.py` re-exports one new top-level name (`MultiOrgAttestationReplicator`); the Tag-6 module re-uses (does NOT re-define) the Tag-2 `MultiOrgAttestationReplicationConflictPolicy`, `MultiOrgAttestationReplicationDecision`, `MultiOrgAttestationReplicationFilter`, `MultiOrgAttestationReplicationMetrics`, `MultiOrgAttestationWatchEvent`, `MultiOrgAttestationWatchOp`, `open_watch_stream`, `MultiOrgAttestationCasConflict`, `MultiOrgAttestationMonotonicConflict`, `MultiOrgAttestationEnvelopeError` types byte-precisely (zero churn on the Tag-2 public surface). **Tests** — 7 new T-MOA-LTR-01..07 in `wirelang/tests/test_federation_multi_org_attestation_live_tail_replicator.py`: T-MOA-LTR-01 bootstrap + live PUT roundtrip (`events_applied_put` advances + `last_revision` reflects live tail), T-MOA-LTR-02 live-tail DELETE removes target entry (`events_applied_delete` advances), T-MOA-LTR-03 `run(bootstrap=False)` skips bootstrap (only live counters advance, seed NOT propagated), T-MOA-LTR-04 filter `only_partner_a` skips partner-b live PUT (`events_skipped_by_filter` advances + partner-b key absent from target), T-MOA-LTR-05 SOURCE_WINS monotonic-breach refused on live tail (`monotonic_breaches` advances + target byte-equal preserved), T-MOA-LTR-06 CAS_PIN out-of-band-bump race-window via byte-equal-idempotent put on target between `get_with_revision` and `put_with_revision` (`cas_conflicts` advances + replicator continues + subsequent unrelated key lands cleanly), T-MOA-LTR-07 `last_revision` resume-cursor monotonic-tracking (advances on apply AND filter-skip; lower-revision synthetic event replay does NOT regress cursor). Test-suite stand: `wirelang/tests` **1010 passed, 1 skipped, 7 subtests passed**. Δ **+7 net** über Tag-5-Baseline-1003. **M-2 conformance preserved**: Tag-1 substrate, Tag-2 backend (envelope codec + monotonic gate + CAS-pin helper + watch-stream + bootstrap helper), Tag-3 bridge, Tag-4 chain-verifier, Tag-5 exporter all byte-equal-untouched (additive Tag-6 module only — the replicator consumes Tag-2 surfaces, never mutates them; the `wakir.federation.multi-org-attestation/1` per-record envelope is byte-unchanged). **M-4 conformance preserved**: orthogonal to wirelangversion axis. **Cross-Review-Zone-O-Status**: D-1 (Tomás WAT-Audit-Federation-Annex) — Tag-6 replicator is consumer-side of the Tag-2 attestation backend; no new WAT-anchor surface (the bridge resolution + chain verification + unrevoke audit marker leaf-anchor surfaces from Tag-3..5 remain the WAT-Audit-Federation-Annex consumption targets). D-2 (Kai SPIRE-Federation-Bundle-Endpoint) — Tag-6 is Kai-track-orthogonal (durable replication is a wirelang-internal continuous-sync concern). D-3 (Júlia NLnet-Antrag-Konsistenz) — Tag-6 closes the cross-bucket replication suite for the multi-org-attestation registry, the V-908-federation-vision-block's persistence axis; Júlia-v1.2-Patches already documented the Sprint-7 trajectory including the Tag-2 bootstrap + Tag-6 live-tail composition reference, so Tag-7 NLnet-Antrag-Konsistenz-Check is **faktisch erledigt** (optional Cross-Reference-Annex remains for the Sprint-7-Closeout doku, NIEDRIG). D-4 (Aisha Eröffnungs-Marker) — bei 3/3 Acks. ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash (no Agent-Tool, no WebFetch). ADR-0049 Pre-Box-Worktree `/tmp/reza-sprint-7-tag-6-runtime` with `-runtime` suffix from Tag-5-Tip `d0669f9`. **Folge-Items Sprint-7 Tag-7..Tag-8**: Tag-7 NIEDRIG NLnet-Antrag-Konsistenz-Check D-3 Júlia post-Ack **faktisch erledigt** (optional Cross-Reference-Annex zur Sprint-7-Closeout-Doku); Sprint-7-Closeout-Vorbereitung Tag-8 (Sprint-6-Pattern: Tomás/Kai/Selin Closeout-Skizze). Additive-only change relative to v0.27.0. |
| 0.27.0  | 2026-05-12 | Phase-2 Sprint-7 Tag-5 lands the **UnrevokeAuditMarker Cross-Org-Export-Surface** as the Pseudonymisierung-Pattern-per-ADR-0031-D4 boundary between the Sprint-6 Tag-9 internal `UnrevokeAuditMarker` (carrier of operator-prose `unrevoke_reason` + `previous_revocation_reason`) and any cross-org publication. New module `wirelang.federation.unrevoke_audit_marker_cross_org_export` (NEW, ~620 LOC incl. module docstring + ~330 test-LOC) ships: (1) `UnrevokeAuditMarkerCrossOrgExporter` frozen-dataclass stateless exporter with synchronous `export(*, marker, attestation) -> ExportedUnrevokeAuditMarker` surface (no async path — pseudonymisation is a pure-function gate, not an I/O orchestrator); (2) `ExportedUnrevokeAuditMarker` frozen result-record carrying seven fields (`export_schema`, `route_id`, `marker_id`, `previous_revoked_at`, `unrevoke_reason_class`, `previous_revocation_reason_hash`, `exported_at`) with constructor-invariants on every shape gate (schema-pin, non-empty route_id, 32-byte BLAKE2b-256 marker_id, tz-aware datetimes, hex-string-or-None reason_hash, raw-narrative-leak defence-in-depth gate); (3) `UnrevokeReasonClass` str-enum with five categorical values (`UNSPECIFIED`, `OPERATOR_RECOVERY`, `POLICY_AMENDMENT`, `INVESTIGATION_CLEARED`, `OTHER`) — the categorical surface that replaces raw `unrevoke_reason` text in the export; (4) pluggable `UnrevokeReasonClassifier` Protocol with `classify(raw: Optional[str]) -> UnrevokeReasonClass` surface — hermetic test fixture `_FakeSubstringClassifier`, default classifier `_DefaultUnrevokeReasonClassifier` maps every present reason to `OTHER` and absent to `UNSPECIFIED` (fail-safe); (5) `EXPORT_SCHEMA = "wakir.federation.unrevoke-audit-marker-export/1"` schema-URI for the WAT-Audit-Federation-Annex (Tomás D-1, forthcoming) leaf-anchoring (mirrors the Tag-3 `BRIDGE_RESOLUTION_SCHEMA` and Tag-4 `CHAIN_VERIFICATION_SCHEMA` convention); (6) `_route_scoped_reason_hash(route_id, raw)` BLAKE2b-256-keyed pseudonymisation primitive — the key is the UTF-8-truncated route_id (≤64 B) and personalisation is the fixed module constant `b"wakir-ump-1\x00\x00\x00\x00\x00"` (16 B); the route-scoped key prevents cross-route equality-correlation on the resulting hex digest (a peer cannot accumulate a cross-route reason-fingerprint database from observing exports under two different routes); (7) `_compute_marker_id(route_id, previous_revoked_at, reason_class, reason_hash)` BLAKE2b-256 digest over a JCS-canonicalised payload mixing the export-schema, route-id, previous-revoked-at (ISO-8601 UTC), reason-class enum-value, and the optional reason-hash — notably **excludes** `exported_at` so re-exports of byte-equal source markers under the same route_id yield byte-equal `marker_id` (timing-invariant audit-leaf identifier across re-exports). **Failure-mode hierarchy** (all parented on `MultiOrgSubstrateError` so existing catch-base callers absorb every exporter surface uniformly): `UnrevokeAuditMarkerCrossOrgExportError` base, `UnrevokeAuditMarkerShapeError` (malformed marker / attestation, classifier-contract breach: non-enum return, None-input-not-UNSPECIFIED), `RawNarrativeLeakError` (defence-in-depth: subclass attempting to carry a raw narrative field `unrevoke_reason` or `previous_revocation_reason` on the envelope is rejected by `ExportedUnrevokeAuditMarker.__post_init__` — structured `field_name`/`type_name` fields). The exporter is **fail-closed at every shape gate**; a malformed marker yields no partial export. Exporter is `frozen=True` dataclass, holds no mutable state, safe for concurrent use. **Pseudonymisation pattern (ADR-0031 D4 alignment)**: ADR-0031 D4 specifies for Persona-Identity-Cross-Org-Resolution "Public-Key + Rolle, kein Klarname" (public key + role descriptor, no clear name). The same logic applies axis-by-axis to audit-trail fields: cross-org export reveals **structure** (an unrevoke happened, at this timing, in this category) without revealing **narrative** (operator's free-form prose). Treatment table: `previous_revoked_at` retained raw (timing-only, no identity); `unrevoke_reason` raw → **stripped**; `unrevoke_reason_class` retained (categorical, finite-set); `previous_revocation_reason` raw → **stripped**; `previous_revocation_reason_hash` BLAKE2b-256-keyed by route_id (equality-comparable, not reversible); `route_id`/`schema`/`marker_id`/`exported_at` retained raw (no identity surfaces). The exporter does NOT export the source-org `registered_by_publisher` (lives on the record-envelope, not on the marker — cross-org export consumes the marker, not the record, so operator-identity leak is structurally impossible from this surface). Federation `__init__.py` re-exports 10 new top-level names (`UnrevokeAuditMarkerCrossOrgExporter`, `ExportedUnrevokeAuditMarker`, `UnrevokeReasonClass`, `UnrevokeReasonClassifier`, `DEFAULT_CLASSIFIER`, `EXPORT_SCHEMA`, `UnrevokeAuditMarkerCrossOrgExportError`, `UnrevokeAuditMarkerShapeError`, `RawNarrativeLeakError`). **Tests** — 7 new T-UMCX-01..07 in `wirelang/tests/test_federation_unrevoke_audit_marker_cross_org_export.py`: happy-path with default classifier yielding `OTHER` class + 64-char hex reason_hash + 32-byte marker_id + raw-text-not-leaked check, absent-reason path yielding `UNSPECIFIED` + `None` reason_hash + marker_id still computes, route-scoped reason-hash determinism + route-scoping defence (same raw under two routes → different hashes), pluggable classifier extension via `_FakeSubstringClassifier` mapping "amend" → `POLICY_AMENDMENT` (and raw text still stripped from envelope), raw-narrative-leak defence (subclass declaring `unrevoke_reason` class attribute rejected by `__post_init__`), marker_id round-trip timing-invariance (re-export under different exporter-clock yields byte-equal marker_id, distinct exported_at), marker_id route-binding (same marker under two different attestation route_ids yields two different marker_ids + two different reason-hashes). Test-suite stand: `wirelang/tests` **1003 passed, 1 skipped, 7 subtests passed**. Δ **+7 net** über Tag-4-Baseline-996. **M-2 conformance preserved**: Tag-1 substrate, Tag-2 backend, Tag-3 bridge, Tag-4 chain-verifier, Sprint-6 Tag-9 `UnrevokeAuditMarker` constructor + record + classifier all byte-equal-untouched (additive Tag-5 module only — the export-surface consumes the marker, never mutates it). **M-4 conformance preserved**: orthogonal to wirelangversion axis. **Cross-Review-Zone-O-Status**: D-1 (Tomás WAT-Audit-Federation-Annex) — the `EXPORT_SCHEMA` `wakir.federation.unrevoke-audit-marker-export/1` is the third leaf-anchor-surface (sister to Tag-3 `BRIDGE_RESOLUTION_SCHEMA` + Tag-4 `CHAIN_VERIFICATION_SCHEMA`) the annex will consume once the WAT-Audit-Federation-Annex sweep lands; the route-scoped `marker_id` is the load-bearing leaf-anchor field. D-2 (Kai SPIRE-Federation-Bundle-Endpoint) — Tag-5 has no Kai-side dependency; the export-surface is pure-function on top of Sprint-6 Tag-9 internals + Sprint-7 Tag-1 attestation. D-3 (Júlia NLnet-Antrag-Konsistenz) — 24h-Ack-Fenster läuft weiter; the export-surface is the V-908-federation-vision-block's **privacy boundary** for the audit-trail axis (sister to the chain-verifier's defence-in-depth posture); Tag-7-NIEDRIG NLnet-Antrag-Konsistenz-Check now references the explicit Pseudonymisierung-Pattern. D-4 (Aisha Eröffnungs-Marker) — bei 3/3 Acks. ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash (no Agent-Tool, no WebFetch). ADR-0049 Pre-Box-Worktree `/tmp/reza-sprint-7-tag-5-runtime` with `-runtime` suffix from Tag-4-Tip `3e2ebbe`. **Folge-Items Sprint-7 Tag-6..Tag-7**: Tag-6 Multi-Org-Attestation-Live-Tail-Replicator (MITTEL, additive to Tag-2 bootstrap), Tag-7 NLnet-Antrag-Konsistenz-Check D-3 Júlia post-Ack (NIEDRIG). Additive-only change relative to v0.26.0. |
| 0.26.0  | 2026-05-12 | Phase-2 Sprint-7 Tag-4 lands the **CapabilityAttenuationChainVerifier** as the wirelang-side passive defence-in-depth layer that verifies cross-org capability-attenuation chains against three replay-class attack surfaces (attenuation-order-violation, stale-attenuation-replay, cross-org-boundary-violation). New module `wirelang.federation.capability_attenuation_chain_verifier` (NEW, ~1145 LOC incl. module docstring + ~520 test-LOC) ships: (1) `CapabilityAttenuationChainVerifier` frozen-dataclass with synchronous `verify(*, entry, attestation, chain) -> VerifiedAttenuationChain` surface (no async path — chain verification is a pure-function gate, not an I/O orchestrator); (2) `AttenuationLink` frozen-dataclass with five fields (`attenuation_index`, `policy_pointer`, `issued_at`, optional `expires_at`, optional `registered_by`) plus constructor-invariants (non-negative int index, non-empty pointer string, tz-aware datetimes, `expires_at > issued_at`); (3) `ResolvedAttenuationLink` frozen-dataclass pairing each link with its resolved `CapabilityPolicy` and an `is_cross_org` boolean marker; (4) `VerifiedAttenuationChain` frozen result-record carrying `chain_hash` (BLAKE2b-256 over JCS-canonicalised payload), `chain_schema`, `attestation_route_id`, `resolved_links`, `verified_at`, `max_link_age_seconds`; (5) pluggable `PeerCapabilityPolicyResolver` Protocol with `resolve(*, pointer, route_id) -> Optional[CapabilityPolicy]` surface — hermetic test fixtures `_FixedPeerResolver` and `_RaisingPeerResolver`, Phase-2c live impl performs cross-org fetch via federation bundle endpoint or dedicated capability-policy endpoint (TBD per ADR-0031 D4 follow-up); (6) `DEFAULT_MAX_LINK_AGE_SECONDS = 3600` (1 h, aligned with Phase-1b Layer-3 capability-token short-lived-attenuation convention); (7) `CHAIN_VERIFICATION_SCHEMA = "wakir.federation.capability-attenuation-chain/1"` schema-URI for the WAT-Audit-Federation-Annex (Tomás D-1, forthcoming) leaf-anchoring. **Failure-mode hierarchy** (all parented on `MultiOrgSubstrateError` so existing catch-base callers absorb every verifier surface uniformly): `CapabilityAttenuationChainError` base, `AttenuationChainShapeError` (malformed input: empty chain, wrong types, tz-naive timestamps), `AttenuationOrderViolationError` (index regress OR issued_at regress — structured `link_position`/`previous_index`/`current_index`/`previous_issued_at`/`current_issued_at` fields), `StaleAttenuationReplayError` (`now - issued_at > max_link_age_seconds` OR `expires_at <= now` OR future-stamped link — structured `link_position`/`link_issued_at`/`link_expires_at`/`now`/`max_age_seconds`/`cause in {"age_exceeded","expired","future_stamped"}` fields), `CrossOrgBoundaryViolationError` (pointer not in local registry AND not the attested peer pointer OR peer resolver returns None — structured `link_position`/`offending_pointer`/`attested_peer_pointer` fields), `AttenuationLinkRevokedError` (per-link revocation precedence from Sprint-6 Tag-1: revoked policy denies even on otherwise-valid chain — structured `link_position`/`offending_pointer`/`revoked_at`/`revocation_reason` fields). The verifier is **fail-closed at every step**; no partial-verification surface. Verifier is `frozen=True` dataclass, holds no mutable state, safe for concurrent use. **Two-surface resolution contract**: for each hop, the verifier first consults the source-org `CapabilityPolicyRegistry` (Sprint-6 Tag-1); on miss, IF the pointer equals `attestation.peer_capability_policy_pointer` AND a peer resolver is configured, the verifier delegates to `peer_resolver.resolve(...)`; any other miss is a graft. **Defence-in-depth posture**: the verifier extends the Sprint-4 Tag-6 / Sprint-6 Tag-1 capability-policy gate from a single-decision check to a chain-level check covering replay patterns the gate alone cannot detect. Cross-references: Tag-1 substrate `wirelang/federation/multi_org_substrate.py` (consumes `peer_capability_policy_pointer`), Tag-2 backend (relies on `peer_capability_policy_pointer` additive-monotonic invariant), Tag-3 bridge (sister-pattern fail-closed orchestrator), Sprint-6 Tag-1 `wirelang/schemas/registered_by_capability.py` (`CapabilityPolicy` + `CapabilityPolicyRegistry` + revocation precedence), Sprint-6 Tag-6 cross-bucket replication. Federation `__init__.py` re-exports 12 new top-level names (`CapabilityAttenuationChainVerifier`, `AttenuationLink`, `ResolvedAttenuationLink`, `VerifiedAttenuationChain`, `PeerCapabilityPolicyResolver`, `CHAIN_VERIFICATION_SCHEMA`, `DEFAULT_MAX_LINK_AGE_SECONDS`, plus five error-types). **Tests** — 9 new T-CACV-01..09 in `wirelang/tests/test_federation_capability_attenuation_chain_verifier.py`: happy-path (3-hop chain — two local hops + one cross-org hop landing on attested peer pointer), attenuation-order-violation by index regress, attenuation-order-violation by issued_at regress, stale-link `age_exceeded` cause, stale-link `expired` cause via `expires_at <= now`, cross-org-boundary-violation pointer-not-in-either-surface, cross-org-boundary-violation peer-resolver-returns-None, revoked-link denial (Sprint-6 Tag-1 revocation precedence per-hop), idempotent re-verify produces byte-equal `chain_hash` despite different `verified_at`. Test-suite stand: `wirelang/tests` **996 passed, 1 skipped, 7 subtests passed**. Δ **+9 net** über Tag-3-Baseline-987. **M-2 conformance preserved**: Tag-1 substrate, Tag-2 backend, Tag-3 bridge, Sprint-6 Tag-1 capability-policy registry all byte-equal-untouched (additive Tag-4 module only). **M-4 conformance preserved**: orthogonal to wirelangversion axis. **Cross-Review-Zone-O-Status**: D-1 (Tomás WAT-Audit-Federation-Annex) — Tag-4 Capability-Substrate-Tier ist Tomás-D-1-Audit-bezogen; the `CHAIN_VERIFICATION_SCHEMA` is the second leaf-anchor-surface (sister to Tag-3 `BRIDGE_RESOLUTION_SCHEMA`) the annex will consume once the WAT-Audit-Federation-Annex sweep lands; 24h-Ack-Fenster läuft weiter. D-2 (Kai SPIRE-Federation-Bundle-Endpoint) — verifier sits downstream of the Tag-3 bridge resolution; no new Kai-side dependency. D-3 (Júlia NLnet-Antrag-Konsistenz) — 24h-Ack-Fenster läuft weiter; the verifier is a substantive realisation of the V-908 federation vision-block's defence-in-depth posture. D-4 (Aisha Eröffnungs-Marker) — bei 3/3 Acks. ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash (no Agent-Tool, no WebFetch). ADR-0049 Pre-Box-Worktree `/tmp/reza-sprint-7-tag-4-runtime` with `-runtime` suffix from Tag-3-Tip `0908d85`. **Folge-Items Sprint-7 Tag-5..Tag-7**: Tag-5 UnrevokeAuditMarker Cross-Org-Export-Surface (MITTEL, Pseudonymisierung pro ADR-0031 D4), Tag-6 Multi-Org-Attestation-Live-Tail-Replicator (MITTEL, additive to Tag-2 bootstrap), Tag-7 NLnet-Antrag-Konsistenz-Check D-3 Júlia post-Ack (NIEDRIG). Additive-only change relative to v0.25.0. |
| 0.25.0  | 2026-05-12 | Phase-2 Sprint-7 Tag-3 lands the **SpiffeCrossTrustDomainBridge** live component as the wirelang-side counterpart to the Tag-1 mock-bridge resolver, paired with the Kai Sprint-6 PR #3 Phase-2 SPIFFE-Infrastructure merge (SPIRE-Server-Sidecar Phase-2.1, SPIRE-Agent-Sidecar Phase-2.2, NATS-JWT-Auth Phase-2.4, Trust-Bundle-Rotation runbook Phase-2.6, Quadlet-SPIRE Tag-11). New module `wirelang.federation.spiffe_cross_trust_domain_bridge` (NEW, ~700 LOC + ~360 test-LOC) ships: (1) `SpiffeCrossTrustDomainBridge` frozen-dataclass orchestrator with `async resolve(route_id, *, peer_svid_token=None, peer_svid_audience=None) -> LiveBridgeResolution`; (2) pluggable `PeerTrustBundleFetcher` Protocol — hermetic test fixtures supply pre-canned bundles, Phase-2c live impl performs SPIFFE Federation Bundle Endpoint HTTPS fetch; (3) pluggable `PeerSvidVerifier` Protocol — hermetic test fixtures accept/reject pre-canned tokens, Phase-2c live impl performs JWKS-based signature verification; (4) `FetchedTrustBundle` and `VerifiedPeerSvid` wirelang-owned frozen value objects (NOT re-exports of any upstream `spiffe` types — pattern-mirror on the Sprint-6 Tag-5 `JwtSvid` / `X509Svid` adapter-layer-indirection contract); (5) `LiveBridgeResolution` frozen result-record carrying entry, attestation, trust-bundle, optional verified peer SVID, optional local-workload SVID (from injected `SpiffeWorkloadApiAdapter`); (6) `DEFAULT_BUNDLE_MAX_AGE_SECONDS = 86400` (24 h, operationally aligned with Kai Phase-2.6 trust-bundle-rotation runbook cadence); (7) `BRIDGE_RESOLUTION_SCHEMA = "wakir.federation.spiffe-cross-trust-domain-bridge/1"` schema-URI for the WAT-Audit-Federation-Annex (Tomás D-1, Sprint-7 Tag-4+) leaf-anchoring. **Failure-mode hierarchy** (all parented on `MultiOrgSubstrateError` so existing catch-base callers absorb every bridge surface uniformly): `SpiffeCrossTrustDomainBridgeError` base, `PeerTrustBundleFetchError` (transport / non-200 / malformed JWKS / trust-domain-mismatch / missing-URL — `url` and `cause` structured fields), `PeerTrustBundleExpiredError` (`fetched_at + bundle_max_age >= now` enforcement; future-stamped bundles also rejected — structured `url`/`fetched_at`/`now`/`max_age_seconds` fields), `PeerSvidSignatureError` (verifier failure or SPIFFE-ID trust-domain prefix double-check breach — structured `trust_domain`/`spiffe_id`/`cause` fields). The bridge is **fail-closed at every step**; no partial-resolution surface. Mock attestations (`is_mock=True`) are rejected at the bridge surface (symmetric with the Tag-1 mock resolver's `is_mock=False` reject — the two paths remain structurally parallel by design). Bridge is `frozen=True` dataclass, holds no mutable state, safe for concurrent use from multiple asyncio tasks. Cross-references: Tag-1 substrate `wirelang/federation/multi_org_substrate.py`, Tag-2 backend `wirelang/federation/multi_org_attestation_nats_kv_backend.py`, Sprint-6 Tag-5 SPIFFE adapter `wirelang/adapters/spiffe_workload_api.py`, Kai Sprint-6 PR #3 `compose/spire.yaml` + `scripts/nats_jwt_callback_skizze.py` + `docs/spire-trust-bundle-rotation.md` + `quadlet/wakir-spire-*`, ADR-0031 D4 `did:web` audit-anchor default, V-908 NLnet-Antrag federation vision-block. Public-surface re-exports added to `wirelang/federation/__init__.py` (12 new top-level names). **Tests** — 10 new T-SCTDB-01..10 in `wirelang/tests/test_federation_spiffe_cross_trust_domain_bridge.py`: happy-path (peer-SVID + local-SVID via `MockSpiffeWorkloadApiAdapter`), unknown route_id, missing attestation, mock attestation rejected, missing `peer_trust_bundle_url`, fetcher exception wrapped with cause, fetched-bundle trust-domain mismatch, stale-bundle expiry, verifier-rejection wrapped with cause, SPIFFE-ID trust-domain prefix double-check (cross-domain spoof attempt). Test-suite stand: `wirelang/tests` **987 passed, 1 skipped, 7 subtests passed**. Δ **+10 net** over Tag-2-baseline-977. **M-2 conformance preserved**: Tag-1 substrate and Tag-2 backend modules byte-equal-untouched (additive Tag-3 module only). **M-4 conformance preserved**: orthogonal to wirelangversion axis. **Cross-Review-Zone-O-Status**: D-1 (Tomás WAT-Audit-Federation-Annex) — 24 h Ack-Fenster läuft parallel; the bridge `BRIDGE_RESOLUTION_SCHEMA` is the surface Tomás-side WAT-anchor-consumer will reference once the WAT-Audit-Federation-Annex sweep lands. D-2 (Kai SPIRE-Federation-Bundle-Endpoint) — **the live-bridge wire-up substrate that motivated the 24 h Ack-Fenster is now on main** (Sprint-6 PR #3 merge); the bridge is the Reza-side consumer-form. D-3 (Júlia NLnet-Antrag-Konsistenz) — 24 h Ack-Fenster läuft parallel; the bridge is a substantive realisation of the V-908 federation vision-block. D-4 (Aisha Eröffnungs-Marker) — bei 3/3 Acks. ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash (no Agent-Tool, no WebFetch). ADR-0049 Pre-Box-Worktree `/tmp/reza-sprint-7-tag-3-runtime` with `-runtime` suffix from post-Sprint-6-Bundle-Merge main-tip `b810dd9`, chained on Tag-2 β-tip `4cb1c7e` (Tag-3 substantively depends on the Tag-2 `MultiOrgRouteAttestation` backend surface). **Folge-Items Sprint-7 Tag-4..Tag-7**: Tag-4 Capability-Attenuation-Chain-Verifier (MITTEL, consumes `peer_capability_policy_pointer`), Tag-5 UnrevokeAuditMarker Cross-Org-Export-Surface (MITTEL), Tag-6 Multi-Org-Attestation-Live-Tail-Replicator (MITTEL, additive to Tag-2 bootstrap), Tag-7 NLnet-Antrag-Konsistenz-Check D-3 Júlia post-Ack (NIEDRIG). Additive-only change relative to v0.24.0. |
| 0.24.0  | 2026-05-12 | Phase-2 Sprint-7 Tag-2 lands the **MultiOrgAttestationNatsKvBackend** durable backend for the `wakir-multi-org-attestations` bucket as the production-target persistence layer over the Sprint-7 Tag-1 `MultiOrgRouteAttestation` substrate. New module `wirelang.federation.multi_org_attestation_nats_kv_backend` (NEW, ~870 LOC) ships: (1) `NatsKvMultiOrgAttestationRegistry` async backend with `get` / `get_with_revision` / `put` / `put_with_revision` / `delete` / `list_keys` / `snapshot` / `watch`; (2) `BUCKET_NAME = "wakir-multi-org-attestations"` plus documented `BUCKET_CONFIG` drift-policy mirror of the Sprint-3 Tag-6 route-registry bucket (history=5, ttl_seconds=0, max_value_size=4096 B, storage="file", replicas=1); (3) **authority-gesture monotonic-invariant gate** — `_check_monotonic_invariant` runs BEFORE every write (`put` AND `put_with_revision`); once a non-mock attestation is recorded for a `route_id`, the authority anchors (`peer_trust_domain`, `peer_audit_anchor_did`) are immutable, the `is_mock` flag is immutable, and optional fields (`peer_wat_anchor_manifest_id`, `peer_trust_bundle_url`, `peer_capability_policy_pointer`) are additive-monotonic (None -> value accepted; value -> None or value-A -> value-B refused); idempotent byte-equal rewrites always pass; a breach surfaces as `MultiOrgAttestationMonotonicConflict` carrying `route_id`, `breach_kind`, `existing`, `incoming`; (4) **CAS-pinned upsert** — `put_with_revision(att, expected_revision)` (pattern-mirror on Sprint-5 Tag-4 capability-policy CAS-pin and Sprint-3 Tag-3 schema-registry CAS-pin); stale-revision rejection surfaces as `MultiOrgAttestationCasConflict` carrying `route_id`, `expected_revision`, `actual_revision`; helper `_kv_update_with_revision` accepts three KV adapter shapes (`update(key, value, last=...)`, positional fallback, `put(key, value, expected_revision=...)`); gate ordering is `isinstance(att) → expected_revision validation → monotonic-invariant → CAS-pin` (monotonic runs BEFORE CAS so a stale-revision race cannot un-set an authority anchor); (5) **Watch-stream layer** — `MultiOrgAttestationWatchOp` enum (PUT/DELETE/PURGE), `MultiOrgAttestationWatchEvent` frozen dataclass with `op`/`route_id`/`attestation`/`revision`, `_WatchStreamHandle` async-iter wrapper accepting both `__aiter__` (Shape 1) and `await updates()` (Shape 2) underlying watchers, `open_watch_stream(backend)`; (6) **LiveSnapshot** — `LiveMultiOrgAttestationSnapshot` with `from_backend()` bootstrap, `apply(WatchEvent)` delta application bypassing `InMemoryMultiOrgAttestationRegistry.add()`'s conflict-rejection (the watch-stream is a strict suffix of the durable bucket history per Sprint-5 Tag-5 contract; producer-side monotonic gate already ran), `as_registry()` frozen-copy with determinism contract (subsequent applies do NOT mutate the returned registry), `last_revision` monotonic-tracking; (7) **Cross-bucket replication** — `MultiOrgAttestationReplicationConflictPolicy` enum (SOURCE_WINS / CAS_PIN), `MultiOrgAttestationReplicationDecision` enum (APPLY / SKIP), `MultiOrgAttestationReplicationFilter` Callable type, `MultiOrgAttestationReplicationMetrics` dataclass with ten counters (`bootstrap_applied`, `bootstrap_skipped_by_filter`, `bootstrap_skipped_idempotent`, `bootstrap_monotonic_breaches`, `events_applied_put`, `events_applied_delete`, `events_skipped_by_filter`, `cas_conflicts`, `monotonic_breaches`, `envelope_errors`), `bootstrap_multi_org_attestation_target_from_source(source, target, policy, filter_fn, metrics)` async bootstrap with idempotency (byte-equal target-side records counted as `bootstrap_skipped_idempotent`), monotonic-breach refusal (counted as `bootstrap_monotonic_breaches` under both SOURCE_WINS and CAS_PIN policies via in-band backend gate), filter-rejection counted as `bootstrap_skipped_by_filter`, sorted-key iteration for determinism. Envelope codec `_attestation_to_envelope` / `_envelope_to_attestation` uses JCS-compatible sorted-keys + compact separators; envelope validation delegates to the Tag-1 substrate constructor (a substrate `MultiOrgAttestationValidationError` is re-raised as `MultiOrgAttestationEnvelopeError` so the backend layer has a single typed error surface for "bad bytes in the bucket"). Error hierarchy: `MultiOrgAttestationBackendError` ← `MultiOrgSubstrateError` (so callers catching the Tag-1 base type also catch backend-layer errors); subtypes `MultiOrgAttestationEnvelopeError`, `MultiOrgAttestationCasConflict`, `MultiOrgAttestationMonotonicConflict`. Federation `__init__.py` re-exports the three top-level backend surfaces (registry, live snapshot, bootstrap function). Tests `wirelang/tests/test_federation_multi_org_attestation_nats_kv_backend.py` (NEW, 15 tests T-MOA-NKV-01..15): single-key round-trip, get-unknown-returns-None, monotonic-breach refusal at `put`, poisoned envelope, snapshot materialisation, bucket-config drift protection, CAS-pin round-trip (create-if-absent + idempotent rewrite), CAS-pin stale-revision conflict with carried metadata, watch yields PUT events, watch yields DELETE event, LiveSnapshot bootstrap + apply + frozen-copy determinism, mock/live transition substrate-guard, optional-field additive-monotonic (None→value accepted, value→None and value-A→value-B refused), cross-bucket bootstrap copy + idempotent re-run, bootstrap monotonic-breach counted under SOURCE_WINS. Test bilanz `wirelang/tests`: 977 passed, 1 skipped, 7 subtests passed (Δ +15 net über Sprint-7 Tag-1 baseline 962). M-2 conformance preserved (Tag-1 substrate untouched; backend is additive). M-4 conformance preserved (orthogonal zur `wirelangversion` axis). Cross-Review Zone-O status (renamed from Zone-D per Mira-Hand 2026-05-12 to avoid collision with Phala-Cloud × V-904 Zone-D): D-1 Tomás-WAT-Audit-Federation-Annex 24h-Ack-Fenster läuft parallel (`peer_wat_anchor_manifest_id` shape is the consumed surface); D-2 Kai-SPIRE-Federation-Bundle-Endpoint 24h-Ack-Fenster läuft parallel (`peer_trust_domain` + `peer_trust_bundle_url` are the consumed surface, live bridge Tag-3+); D-3 Júlia-NLnet-Antrag-Konsistenz 24h-Ack-Fenster läuft parallel (substrate-tier of multi-org federation is the NLnet-Antrag V-908 reference); D-4 Aisha-Eröffnungs-Marker bei 3/3 Acks; Sprint-7-Tag-2-Substrate-Iteration läuft unabhängig (Mira-Decision: Substrate ist Zone-O-Konsens-Substanz, kein Sprint-Block). ADR-0050 Tool-Surface-Stempel: Read, Edit, Write, Bash (kein Agent-Tool, kein WebFetch). ADR-0049 Pre-Box-Worktree `/tmp/reza-sprint-7-tag-2-runtime` mit `-runtime`-Suffix aus Tag-1-Tip `9aef092`. Folge-Items: Tag-3 `SpiffeCrossTrustDomainBridge` Live-Component paired Kai SPIRE-Federation-Bundle-Endpoint (D-2-bezogen); Tag-4 Capability-Attenuation-Chain-Verifier; Tag-5 `UnrevokeAuditMarker` Cross-Org-Export-Surface (Pseudonymisierung pro ADR-0031 D4); Tag-7 NLnet-Antrag-Konsistenz-Check (D-3 Júlia post-Ack). |
| 0.23.0  | 2026-05-12 | Phase-2 Sprint-7 Tag-1 lands the **Multi-Org Federation Substrate** (Phase-3-preparation) as the additive composition layer over the Sprint-3 Tag-6 `wakir-federation-routes` NATS-KV bucket. New module `wirelang.federation.multi_org_substrate` (NEW, ~330 LOC) ships: (1) `MultiOrgRouteAttestation` frozen dataclass with seven fields (`route_id`, `peer_trust_domain`, `peer_audit_anchor_did`, optional `peer_wat_anchor_manifest_id`, optional `peer_trust_bundle_url`, optional `peer_capability_policy_pointer`, `is_mock: bool`) plus constructor-invariants (SPIFFE trust-domain grammar regex, did:web grammar regex, https:// URL constraint on bundle URL, mock-prefix-consistency invariant in both directions); (2) `ATTESTATION_VALUE_SCHEMA = "wakir.federation.multi-org-attestation/1"` schema-URI constant for the forthcoming Tag-2 NATS-KV backend envelope; (3) `MOCK_BRIDGE_ROUTE_ID_PREFIX = "mock-bridge://"` reserved prefix; (4) `InMemoryMultiOrgAttestationRegistry` reference registry (mirrors the Phase-1b `InMemoryRouteRegistry` shape; `add()` is idempotent on byte-equal re-adds and raises `MultiOrgAttestationConflictError` on conflicting re-adds; CAS-protected updates land in Tag-2 backend); (5) `MockBridgeResolution` frozen dataclass pairing a `RouteRegistryEntry` with its `MultiOrgRouteAttestation`; (6) `resolve_mock_bridge_route` function with four fail-closed failure modes (`UnknownBridgeRouteError` for unknown route, missing attestation, non-mock attestation, bad prefix); (7) `MultiOrgSubstrateError` base exception + three subtypes (`MultiOrgAttestationValidationError`, `MultiOrgAttestationConflictError`, `UnknownBridgeRouteError`). The Sprint-3 Tag-6 `RouteRegistryEntry` shape is preserved byte-equally — single-org route entries are untouched by this additive layer; the multi-org attestation is a side-table keyed by `route_id`. ADR-0031-Substrate-Voraussetzungs-Mapping S-1..S-4 covered: S-1 Cross-Org-Identity-Resolution via `peer_audit_anchor_did`; S-2 Cross-Org-Audit-Federation via `peer_wat_anchor_manifest_id` (Tomás D-1); S-3 Cross-Org-Capability-Token-Federation via `peer_capability_policy_pointer`; S-4 Cross-Trust-Domain-SPIFFE-Bridge via `peer_trust_domain` + `peer_trust_bundle_url` (Kai D-2). 16 new tests T-MOS-01..T-MOS-08 in `wirelang/tests/test_multi_org_substrate.py` (8 named buckets across multiple sub-tests, all passing): T-MOS-01 schema-conformance round-trip; T-MOS-02 mock-bridge-route round-trip via `resolve_mock_bridge_route`; T-MOS-03 / T-MOS-03b / T-MOS-03c fail-closed unknown-route + missing-attestation + bad-prefix; T-MOS-04 / T-MOS-04b / T-MOS-04c mock/live confusion guards (construction-time bidirectional + resolver-level); T-MOS-05 / T-MOS-05b / T-MOS-05c grammar validation (trust-domain + did:web + https-only bundle URL); T-MOS-06 / T-MOS-06b conflict semantics (idempotent + rejecting); T-MOS-07 optional-fields-all-None; T-MOS-08 single-org-orthogonality regression guard; T-MOS-aux schema-constant pin. Mira-Eskalations-Punkt E1 (ADR-0031) status: A2A-Spec §4.x befund classifies the constraint as **unkritisch** (memo `reza/outbox/2026-05-12-a2a-spec-§4-x-befund-fuer-mira.md`) — A2A §4.x neither mandates nor forbids DID-document emission; substrate is therefore not gated on E1, only live federation trial (Sprint-8+) remains Mira-Hand approval-pending. Cross-Review-Zone status: Z-1 / Z-2 / Z-A / Z-B / Z-M non-touched; new **Zone-D** (Multi-Org-Federation-Substrate) opened with four trigger-items D-1 (Reza × Tomás WAT-Audit-Federation), D-2 (Reza × Kai SPIFFE-Cross-Trust-Domain-Bridge), D-3 (Reza × Selin NLnet-Antrag-Konsistenz), D-4 (Reza × Aisha Cross-Review-Moderation). M-2 conformance preserved (additive only; existing single-org `RouteRegistryEntry` envelopes byte-equal-unchanged). M-4 conformance preserved (orthogonal to the wirelangversion axis). Forthcoming Sprint-7 Tag-2: NATS-KV backend `MultiOrgAttestationNatsKvBackend` for the `wakir-multi-org-attestations` (working name) bucket with watch-stream + CAS-pin + cross-bucket replication composition; Sprint-7 Tag-3: live `SpiffeCrossTrustDomainBridge` component pairing Kai SPIRE-Federation-Bundle-Endpoint configuration (D-2); Sprint-7 Tag-7: NLnet-Antrag-Konsistenz-Check (D-3); Sprint-8+: live federation trial pending Mira-Hand approval. Additive-only change relative to v0.22.0. |
| 0.22.0  | 2026-05-12 | Phase-2 Sprint-6 Tag-9 lands the **`RevocationEventKind.EXPLICIT_UNREVOKE` classifier extension** so consumer-side audit tracks can distinguish operator-deliberate unrevoke (Sprint-6 Tag-7 `publisher-cli unrevoke` subcommand) from accidental `REVOCATION_MONOTONIC_BREACH` (substrate corruption / out-of-band tampering) by reading the watch-stream alone (no cross-reference to a separate receipt channel). Surface additions on `wirelang.schemas.capability_policy_nats_kv_backend`: (1) new sixth `RevocationEventKind.EXPLICIT_UNREVOKE` enum member (additive over the Sprint-6 Tag-3 five-member enum: `NOT_REVOCATION_RELATED`, `REVOCATION_TRANSITION`, `REVOCATION_REFRESH`, `REVOCATION_MONOTONIC_BREACH`, `KEY_REMOVED` — all five preserved byte-equally); (2) new `UnrevokeAuditMarker` frozen dataclass with three fields (`unrevoke_reason: Optional[str]`, `previous_revoked_at: datetime` REQUIRED non-None, `previous_revocation_reason: Optional[str]`) carried on the envelope as an additive optional sub-object; (3) `CapabilityPolicyRecord` gains an additive `unrevoke_audit_marker: Optional[UnrevokeAuditMarker] = None` field with a constructor invariant that REJECTS a marker on a still-revoked policy (`policy.revoked_at is not None` + `unrevoke_audit_marker is not None` → `CapabilityPolicyValidationError`); the constructor invariant is the *structural suppression* that lets the classifier treat marker presence as load-bearing ONLY on the prior-revoked-to-unrevoked transition. Envelope codec additions: `_record_to_envelope` emits the `unrevoke_audit_marker` key ONLY when the marker is non-None (legacy / non-unrevoke write paths produce byte-equal-to-Sprint-6-Tag-8 envelopes); `_envelope_to_record` accepts the key as optional with three required sub-fields when present and decodes back to a fully-formed `UnrevokeAuditMarker` (partial / wrong-shape sub-object → `CapabilityPolicyEnvelopeError`, not silent pass-through). Classifier extension: `RevocationEventClassifier.classify` extends the Sprint-6 Tag-3 decision table with one marker-dependent branch on the `prior-revoked-X` × `incoming-revoked_at=None` transition — marker present AND `marker.previous_revoked_at == prior_revoked_at` (the classifier's per-key prior view) → `EXPLICIT_UNREVOKE`; marker absent OR `marker.previous_revoked_at` mismatching the prior view → `REVOCATION_MONOTONIC_BREACH` (safe-default: the louder kind wins when the gesture cannot be authenticated against the observed prior state). Filter default-kinds extended: `filter_revocation_events(kinds=None)` now defaults to `{REVOCATION_TRANSITION, REVOCATION_REFRESH, REVOCATION_MONOTONIC_BREACH, EXPLICIT_UNREVOKE}` (four revocation-axis kinds — additive over the Sprint-6 Tag-3 three-kind default) so audit consumers see operator-deliberate unrevokes on the same default filter as BREACH (the two are sister kinds on the prior-revoked-to-unrevoked transition); `NOT_REVOCATION_RELATED` and `KEY_REMOVED` remain filtered out by default. Publisher-CLI integration: `_run_unrevoke` (Sprint-6 Tag-7) constructs an `UnrevokeAuditMarker` from `(--unrevoke-reason, live_record.policy.revoked_at, live_record.policy.revocation_reason)` and attaches it to the rewritten `CapabilityPolicyRecord` BEFORE `backend.put()`; the receipt-on-stdout and the envelope-on-wire now carry the same audit fields so the audit trail surfaces it twice (receipt for the operator, envelope for every watch consumer). Backward-compat invariant: every pre-Sprint-6-Tag-9 write path (publish, revoke, replication, Sprint-6 Tag-1..8 paths) produced envelopes without the `unrevoke_audit_marker` key; the decoder treats absence as `unrevoke_audit_marker=None` (back-compat byte-precise); a pre-Tag-9 unrevoke envelope (Sprint-6 Tag-7 happy path) on the watch-stream continues to surface as `REVOCATION_MONOTONIC_BREACH` (the conservative safe default — an unmarked unrevoke is structurally indistinguishable from out-of-band tampering and the consumer decides the response). Forward-compat: the marker is gate-orthogonal (the `CapabilityPolicy` bundle is unchanged by its presence; verifier-side gating reads only `policy.*` fields; the marker is audit-axis state on the record-bookkeeping side); operators can opt-in by upgrading to a Tag-9+ publisher-CLI and watch consumers can opt-in by upgrading to a Tag-9+ classifier — the two upgrades are independent. §6 extended with T-CPP-REVF-13..19 + 1 aux probe in `wirelang/tests/test_revocation_event_filter.py` (8 new tests; preserves T-CPP-REVF-01..12 + 2 aux byte-equally): T-CPP-REVF-13 (positive — marker match → EXPLICIT_UNREVOKE, per-key state advances to None), T-CPP-REVF-14 (negative — marker `previous_revoked_at` mismatch → BREACH), T-CPP-REVF-15 (negative — no marker → BREACH, regression guard on Sprint-6 Tag-3 T-CPP-REVF-05), T-CPP-REVF-16 (record constructor rejects marker on still-revoked policy), T-CPP-REVF-17 (filter default-kinds surface EXPLICIT_UNREVOKE), T-CPP-REVF-18 (envelope round-trip preserves marker byte-equally), T-CPP-REVF-19 (envelope back-compat — pre-Tag-9 envelopes without the key decode with marker=None), T-CPP-REVF-aux-poisoned-marker (defensive: partial marker sub-object raises envelope error). Publisher-CLI tests extended with T-SR-UREV-09..09c in `wirelang/tests/test_publisher_cli_unrevoke.py` (3 new tests; preserves T-SR-UREV-01..08 byte-equally): T-SR-UREV-09 (unrevoke attaches marker to wire-envelope with prior revocation captured + operator unrevoke_reason), T-SR-UREV-09b (unrevoke without `--unrevoke-reason` still writes marker with `unrevoke_reason=None`), T-SR-UREV-09c (marker is per-write transient — a subsequent re-revoke does NOT carry the marker; the record constructor would reject it anyway). Total project-wide test count: 935 (Sprint-6 Tag-8) → 946 (Sprint-6 Tag-9), delta +11 (8 classifier-level + 3 CLI-level). The Sprint-6 Tag-9 path is **additive over Sprint-6 Tag-8 (v0.21.0)**: backend write paths (LWW `put`, CAS-pin `put_with_revision`, Sprint-6 Tag-1 revocation-monotonicity invariant), capability-policy replicator (Sprint-6 Tag-6 — the replicator carries the marker byte-precisely via the same `_record_to_envelope` path; an unrevoke on the source bucket replicates to the target as an `EXPLICIT_UNREVOKE`-classifiable event with the marker intact, NOT a BREACH), publisher-CLI `publish` / `dry-run` / `revoke` subcommands (Sprint-3 Tag-5, Sprint-5 Tag-1+3, Sprint-6 Tag-2), SPIFFE Workload API adapter (Sprint-6 Tag-4+5), federation-route registry (Sprint-2 Tag-4+6), N2 federation evaluator (Sprint-2 Tag-3), N3 chain walker (Sprint-2 Tag-5), datalog-caveat vocabulary v0.2.1 (Sprint-6 Tag-8) — all byte-unchanged. M-2 conformance preserved (the `wakir.wirelang.capability-policy-entry/1` envelope shape is additively extended with one optional sub-object; envelopes WITHOUT the sub-object are byte-equal to the Sprint-6 Tag-8 shape, envelopes WITH the sub-object are forward-compat-decodable by Sprint-6 Tag-3 consumers as `RevocationEventKind.REVOCATION_MONOTONIC_BREACH` — they simply don't surface the new kind, which is the same conservative-safe-default behaviour as marker-less Tag-9 envelopes). M-4 conformance preserved (orthogonal to wirelang version axis). Cross-Review-Zone-1 (Identity-Substrate) non-touched (no cryptographic-substrate touch — the marker is application-layer audit-axis state). Cross-Review-Zone-B (NATS-KV × Wirelang) non-touched (the existing `wakir-capability-policies` bucket configuration is byte-unchanged; the `history=5` audit-trail depth continues to retain pre- and post-unrevoke envelopes). Cross-Review-Zone-A (SPIFFE/SPIRE) non-touched (orthogonal axis). Cross-Review-Zone-M (TV-W manifest) non-touched (orthogonal axis). Phase-3 reservations preserved: production-side `wirelang/canonical/self_reference.py` module (Sprint-6 Tag-8 reservation; Tag-9 does not touch it), Phase-3 bidirectional capability-policy replication and multi-source fan-in (Sprint-6 Tag-6 reservation; Tag-9's marker round-trips byte-precisely through the existing replicator path, so a future bidirectional path inherits the marker semantics for free), `persona_pin` Class-P promotion (residual; awaits its own ADR), Class R substrate roll-out (each its own engineering programme), real-`spiffe`-PyPI-backed `RealSpiffeWorkloadApiAdapter` functional implementation (paired with Kai's DevOps-track SPIRE-server integration; remains Phase-2c, Operator-Hand). Sprint-6 Tag-9+ candidates: full Biscuit v3 binary token revocation/unrevoke-list interpretation (token-level lives in the Phase-3 Datalog substrate; Tag-9 surface remains operator-policy-unrevoke), watch-stream-resume seed for the marker map (the Sprint-6 Tag-3 `seed_from_records` seeds the per-key `revoked_at` map but the marker is stateless across resume — a Phase-3 enhancement could persist the last-observed marker per key for richer resume semantics), CAS-quorum capability-policy distribution (Sprint-6 Tag-6 reservation; Tag-9's marker is per-write and CAS-quorum would carry it byte-precisely without further surface change). Additive-only change relative to v0.21.0. |
| 0.21.0  | 2026-05-12 | Phase-2 Sprint-6 Tag-8 lands the **ADR-0052 Class-P promotion of `caveat_hash`** to N1 via a `datalog-caveat/0.2.0 → 0.2.1` schema patch (`wirelang/schemas/datalog-caveat.json` `$id` bumped to `https://wakir.dev/wirelang/schema/datalog-caveat/0.2.1`; pattern is additive — a dedicated alternation arm `^\s*caveat_hash\(\s*"[0-9a-f]{64}"\s*\)\s*$` admits the canonical literal shape, the first arm with 22 N1∪N2 predicates is byte-unchanged). The vocabulary spec `wirelang/specs/datalog-caveat-vocabulary-phase-2.md` is bumped from v0.2.0 to v0.2.1 with a new §6.7 "v0.2.1 Self-Reference Predicate Verification (ADR-0052)" ratifying the verifier behaviour (wire form §6.7.1, recompute algorithm §6.7.2 with strip + cardinality-gate + recompute + comparison steps, forward-compat with v0.2.0 verifiers §6.7.3, backward-compat invariant §6.7.4, algorithm-self-reference-exclusion-contract §6.7.5 as the load-bearing contract preserving TV-W-2 pin-stability, drift surface impact §6.7.6 documenting the EXPECTED_DELTA re-baseline 149 → 154). §3.4 (Class P) row for `caveat_hash` patched from "reserved" to "promoted to N1 in v0.2.1 (ADR-0052 approved 2026-05-12, landed Sprint-6 Tag-8 2026-05-12)"; §3.4-N1-promoted-slot replaces the prior TODO block with the ratified contract; §3.5 alias reservation extends to `caveat_self_hash` (unchanged from v0.2.0); §5.4 schema implications subsection updated with the v0.2.1 patch note; §7 tabular ratification summary updates the `caveat_hash` row from `P / 1a-patch (deferred) / no / reserved` to `N1 / 1b (NEW v0.2.1, ADR-0052) / yes (NEW v0.2.1) / self-reference recompute per §6.7`; counts post-v0.2.1 are N1 = 19, N2 = 4, R = 6, P = 1 (`persona_pin` residual), schema-admitted = 23. Five new ratification probes (T-CHP-07..11) land in `wirelang/tests/test_caveat_hash_promotion_substrate.py` (Phase B section, additive over the seven Phase A T-CHP-01..06+aux Tag-2 substrate probes): T-CHP-07 (TV-W-2 pin-pack hash byte-stable under promotion, golden `ddf11545…d7532`), T-CHP-08 (caveat-set-hash byte-equal under augment-with-self-reference against three TV-W-2 block-caveat shapes), T-CHP-09 (schema `$id` is 0.2.1 post-promotion), T-CHP-10 (alias `caveat_self_hash` not admitted), T-CHP-11 (schema pattern admits canonical literal but not variants — variable arguments, upper-case hex, wrong-length, unquoted). Five new schema-admission probes (T-V0.2.1-01..05) land in `wirelang/tests/test_datalog_vocabulary_phase_2.py` (additive over the existing T-V0.2-01..04 catalogue): T-V0.2.1-01 (admits canonical lower-case-hex literal), T-V0.2.1-02 (rejects upper-case hex — lower-case canonical only), T-V0.2.1-03 (rejects wrong-length hex literals), T-V0.2.1-04 (rejects unquoted arguments — variable or bare hex), T-V0.2.1-05 (additivity check — every v0.2.0 N1∪N2 caveat shape still validates on v0.2.1). Existing T-V0.2-04 reclassified from "Class P (persona_pin + caveat_hash)" to "residual Class P (persona_pin only)" since `caveat_hash` is now schema-admitted on v0.2.1. The fixture-pinned `assert schema["$id"].endswith("/0.2.0")` in `test_datalog_vocabulary_phase_2.py` is bumped to `endswith("/0.2.1")`. Schema-registry round-trip test (`wirelang/tests/test_schema_registry_nats_kv_backend.py::test_t_sr_aux_key_derivation_round_trip`) extended with a v0.2.1 case so the registry key-space (federation/datalog-caveat/0.2.1) is bijective alongside the existing v0.2.0 case (v0.2.0 entry preserved — the registry tracks every version, not just the newest). `docs/wirelang-schema-inventory.md` row 5 updated to `$id` 0.2.1 with "ADR-0052 Class-P promotion of `caveat_hash`, Sprint-6 Tag-8" description; `wirelang/specs/nats-subject-mapping-v1.md` `cap.token.*` (caveat-set body) row updated from 0.2.0 to 0.2.1. `.github/workflows/tests.yml` `EXPECTED_DELTA` re-baselined from 149 to 154 (drift 5 = tol 5, at-edge) with the §6.3 re-baseline-list item 1 (vocabulary addition triggers schema-admission test additions) as the trigger rationale; the five Phase-B substrate-promotion probes are regex-based and run in BOTH lanes (no drift impact), the five v0.2.1 schema-admission probes are `jsonschema`-gated and run in the production lane only (contribute +5 to the delta). Substance vorlage anchor: the algorithm-self-reference-exclusion contract from Reza's ADR-0052 vorlage is the load-bearing invariant — the recompute algorithm excludes `caveat_hash` from the §4-CSC input set, so the per-block `caveat_set_hashes` pinned in the TV-W-2 golden fixture remain byte-identical (the `pin_pack_sha256` field `ddf11545…d7532` is byte-stable across the promotion, pinned by T-CHP-07). Sprint-6 Tag-8 path is **additive over Sprint-6 Tag-7 (v0.20.0)**: every existing surface is byte-unchanged. Backend write paths (LWW `put`, CAS-pin `put_with_revision`, Sprint-6 Tag-1 revocation-monotonicity invariant), capability-policy replicator (Sprint-6 Tag-6), revocation-event-filter (Sprint-6 Tag-3), publisher-CLI `publish` / `dry-run` / `revoke` / `unrevoke` subcommands (Sprint-3 Tag-5, Sprint-5 Tag-1+3, Sprint-6 Tag-2, Sprint-6 Tag-7), SPIFFE Workload API adapter (Sprint-6 Tag-4+5), federation-route registry (Sprint-2 Tag-4+6), N2 federation evaluator (Sprint-2 Tag-3), N3 chain walker (Sprint-2 Tag-5) — all byte-unchanged. M-2 conformance preserved (no envelope-shape change; the datalog-caveat schema is a leaf-string content-schema, not a transport-envelope schema; the leaf-string admission surface gains the dedicated `caveat_hash` arm strictly additively). M-4 conformance preserved (vocabulary version axis is orthogonal to wirelang version axis; v0.2.0 → v0.2.1 vocabulary patch does NOT shift the wirelang `wirelangversion` baseline). Cross-Review-Zone-1 (Identity-Substrate) non-touched (no Identity-Substrate touch; the promotion is a vocabulary-layer schema patch and a verifier-side algorithm definition, not a cryptographic primitive; the four Z-1-K-Sprint-4 consensus points remain byte-identical). Cross-Review-Zone-B (NATS-KV × Wirelang) non-touched (no bucket-config change; the existing schema-registry bucket `wakir-schemas` continues to track the same datalog-caveat-versioned entries — v0.2.0 and v0.2.1 coexist in the bucket key-space). Cross-Review-Zone-A (SPIFFE/SPIRE) non-touched (orthogonal axis). Cross-Review-Zone-M (TV-W manifest) non-touched (the TV-W-2 pin-pack hash is byte-stable per T-CHP-07; the QA-side cross-component test-vector set surface is unaffected). Phase-3 reservations preserved: `persona_pin` Class-P promotion (residual; awaits its own ADR), Class R substrate roll-out (zk-backend, persona-state registry, WAT manifest resolver, distributed quota counter — each its own engineering programme), production-side `wirelang/canonical/self_reference.py` module (reserved for when a runtime token-evaluator consumes the predicate; the test-side helper in `test_caveat_hash_promotion_substrate.py` carries the canonical algorithm until then). Sprint-6 Tag-8+ candidates: explicit `RevocationEventKind.EXPLICIT_UNREVOKE` enum member on the Sprint-6 Tag-3 classifier (Phase-3 wirelang-roadmap slot — distinguishes operator-deliberate unrevoke from accidental BREACH), real-`spiffe`-PyPI-backed `RealSpiffeWorkloadApiAdapter` functional implementation (paired with Kai's DevOps-track SPIRE-server integration; remains Phase-2c), Phase-3 bidirectional capability-policy replication and multi-source fan-in (reserved Phase-3 slots from Sprint-6 Tag-6). Additive-only change relative to v0.20.0. |
| 0.20.0  | 2026-05-12 | Phase-2 Sprint-6 Tag-7 lands the **publisher-CLI `unrevoke` subcommand** composing an operator-deliberate unrevoke gesture onto the wirelang publisher surface (`wirelang.schemas.publisher_cli`: new `unrevoke` subcommand with flags `--registered-by`, `--policy-id`, `--registered-by-publisher`, `--unrevoke-reason`, `--registered-at`, `--connect-url`; new `UnrevokeReceipt` dataclass with twelve canonical receipt fields including `cmd="unrevoke"`, `mode="lww"` (the unrevoke gesture is structurally LWW because the Sprint-6 Tag-1 backend revocation-monotonic invariant forbids `revoked_at=None` against a live revoked record on the CAS-pin path; an unrevoke is therefore by construction a deliberate LWW write), `previous_revoked_at` / `previous_revocation_reason` capturing the live record's pre-unrevoke revocation state for audit-trail correlation, `previous_revision` / `new_revision` pair, `unrevoke_reason` audit-only field; one new exit code `ExitCode.UNREVOKE_TARGET_NOT_REVOKED = 10` (unrevoke target exists on the bucket but is NOT currently revoked; distinct from `REVOKE_TARGET_NOT_FOUND` so pipelines can disambiguate "policy never existed" from "policy exists but is already unrevoked"; refusing an unrevoke against an unrevoked policy keeps the audit trail crisp — no spurious unrevoke receipts for already-unrevoked policies); new helpers `_add_unrevoke_flags`, `_run_unrevoke`). The flag surface is intentionally narrower than `revoke`: `--lww` and `--expected-revision` are ABSENT by design (the unrevoke path is structurally LWW-only, and a narrow flag surface keeps the operator contract crisp — "there is exactly one way to unrevoke"). `--unrevoke-reason` is surfaced on the receipt for audit traceability but NOT persisted on the rewritten record (the rewritten record is byte-equal to a fresh unrevoked policy modulo `registered_at` and `registered_by_publisher` bookkeeping; downstream pipelines that need the reason MUST capture the receipt JSON alongside the bucket history). The unrevoke gesture is a **separate deliberate authority gesture** (not an "undo" of a prior revoke) so the audit trail can distinguish "policy was revoked and the revocation is still in effect" from "policy was revoked, then unrevoked by an authorised operator at instant T". §5.13 extended with a "Unrevoke subcommand operational contract (Sprint-6 Tag-7, additive over Sprint-6 Tag-2)" subsection (deferred; see operator manpage `docs/publisher-cli-unrevoke.md` for the canonical surface reference). §6 extended with T-SR-UREV-01..08 test inventory (`wirelang/tests/test_publisher_cli_unrevoke.py` NEW, ~610 LOC): T-SR-UREV-01 (happy path: revoked target → unrevoke writes `revoked_at=None` / `revocation_reason=None` via LWW; receipt records `cmd='unrevoke'`, `mode='lww'`, prior revocation state); T-SR-UREV-02 (bundle preservation: every non-revocation capability-bundle field — `allowed_kids`, `allowed_triples`, `disabled`, `note`, `not_before`, `not_after` — byte-equal on the rewritten unrevoked record); T-SR-UREV-03 (target-not-revoked: surfaces `UNREVOKE_TARGET_NOT_REVOKED` (10) with bucket state byte-equal-unchanged); T-SR-UREV-04 (target-not-found: surfaces `REVOKE_TARGET_NOT_FOUND` (9), reused — the "not found" semantics are identical for both subcommands); T-SR-UREV-05 (empty `--registered-by-publisher` rejected pre-connect with INPUT_ERROR (3)); T-SR-UREV-06 (`--unrevoke-reason` audit-only contract: surfaces on receipt but NOT persisted on the rewritten record); T-SR-UREV-07 (argparse-surface narrowness: `--lww` and `--expected-revision` are absent on the unrevoke subcommand; argparse surfaces both as usage error exit 2); T-SR-UREV-08 (revoke → unrevoke round-trip: `unrevoke.previous_revoked_at` byte-equals `revoke.revoked_at`, revisions chain monotonically, subsequent re-revoke at a new instant succeeds because the policy is back in the unrevoked state). The Sprint-6 Tag-7 path is **additive over Sprint-6 Tag-6 (v0.19.0)**: existing `publish` / `dry-run` / `revoke` subcommands, Sprint-5 Tag-1 / Tag-3 capability-gating flag-set, Sprint-5 Tag-2..5 capability-policy backend surfaces, Sprint-6 Tag-1 revocation-monotonic backend invariant, Sprint-6 Tag-3 consumer-side revocation-event-filter, Sprint-6 Tag-4..5 SPIFFE Workload API adapter, and Sprint-6 Tag-6 cross-bucket capability-policy replicator are all byte-unchanged. The unrevoke subcommand touches the SAME bucket as `revoke` (`wakir-capability-policies` only — `wakir-schemas` is NEVER touched by either path) and goes through the existing LWW `put` path of `NatsKvCapabilityPolicyBackend` (the backend itself is NOT modified — the LWW path was always non-monotonicity-enforcing per the Sprint-6 Tag-1 contract). M-2 conformance preserved (no envelope-shape change — the `wakir.wirelang.capability-policy-entry/1` envelope is the Sprint-6 Tag-1 additive shape; the unrevoke is a write-path composition only). M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 non-touched (no Identity-Substrate touch; the unrevoke subcommand is a pure operator-CLI composition; the four Z-1-K-Sprint-4 cryptographic-substrate consensus points remain byte-identical). Cross-Review-Zone-B non-touched (no new bucket; the `wakir-capability-policies` bucket configuration is byte-unchanged — the existing `history=5` audit-trail depth retains the pre-unrevoke envelope for audit). Cross-Review-Zone-A non-touched (orthogonal to SPIRE/SPIFFE axis). Cross-Review-Zone-M non-touched (orthogonal to TV-W manifest axis). Phase-3 reservations preserved: full Biscuit v3 binary token revocation/unrevoke-list interpretation (Tag-7 surface is operator-policy-unrevoke, *not* token-unrevoke; token-level lives in the Phase-3 Datalog substrate); cross-bucket unrevoke-replication (Tag-6 `CapabilityPolicyReplicator` carries unrevoked policies byte-precisely via the same `_record_to_envelope` path; an unrevoke on the source bucket replicates to the target as a `REVOCATION_TRANSITION` from revoked-to-unrevoked, observable through the Sprint-6 Tag-3 classifier as a `KEY_REMOVED`-style transition — Phase-3 hardening item to refine the classifier kind for explicit unrevoke vs. accidental BREACH distinction). Sprint-6 Tag-7+ candidates: ADR-0052 Class-P-Promotion `caveat_hash` implementation (datalog-caveat vocabulary `0.2.0 → 0.2.1` patch + §3.4 N1 promotion; Sprint-7 candidate or Tag-8+ box); real-`spiffe`-PyPI-backed `RealSpiffeWorkloadApiAdapter` (paired with Kai's DevOps-track SPIRE-server integration; remains Phase-2c); explicit `RevocationEventKind.EXPLICIT_UNREVOKE` enum member on the classifier so the Sprint-6 Tag-3 audit-consumer surface can distinguish operator-deliberate unrevoke from accidental BREACH (Phase-3 wirelang-roadmap slot — current Tag-7 behaviour leaves the classifier classifying an unrevoke PUT as `REVOCATION_MONOTONIC_BREACH` because the LWW envelope alone does NOT carry the `cmd="unrevoke"` operator marker; this is acceptable behaviour for Phase-2 since the operator gesture is observable through the receipt JSON, but a Phase-3 envelope addition could carry the marker for in-band audit). Additive-only change relative to v0.19.0. |
| 0.19.0  | 2026-05-12 | Phase-2 Sprint-6 Tag-6 lands the **cross-bucket capability-policy replication** layer for `wakir-capability-policies`, composing the Sprint-5 Tag-2 LWW + Sprint-5 Tag-4 CAS-pin + Sprint-5 Tag-5 watch-stream surfaces with the Sprint-6 Tag-1 revocation-monotonic invariant carried byte-precisely across the cross-bucket boundary. New module `wirelang.schemas.capability_policy_replication` (NEW, ~570 LOC) ships: `CapabilityPolicyReplicationConflictPolicy` enum (`SOURCE_WINS` / `CAS_PIN`); `CapabilityPolicyReplicationDecision` enum (`APPLY` / `SKIP`); `CapabilityPolicyReplicationFilter = Callable[[CapabilityPolicyWatchEvent], CapabilityPolicyReplicationDecision]` type alias; `CapabilityPolicyReplicationMetrics` dataclass with ten counters including the two revocation-specific counters `bootstrap_revocation_breaches` and `revocation_breaches` (independent from `bootstrap_skipped_idempotent` / `bootstrap_skipped_by_filter` / `bootstrap_applied` / `events_applied_put` / `events_applied_delete` / `events_skipped_by_filter` / `cas_conflicts` / `envelope_errors`); `bootstrap_capability_policy_target_from_source(source, target, filter_fn=None, metrics=None)` helper for the initial-sync pass with byte-comparison-idempotency via `_record_to_envelope`; and `CapabilityPolicyReplicator` dataclass (`source` / `target` / `conflict_policy` / `filter_fn` / `halt_on_envelope_error=True` / `halt_on_conflict=False` / `halt_on_revocation_breach=False` / `metrics` fields; `bootstrap()` / `run(*, bootstrap=True)` / `_apply_put` / `_apply_delete` / `_consume_event` methods). The replicator is a thin composition of three Phase-2 substrate surfaces; the new cross-cutting addition is **revocation-monotonic preservation across the cross-bucket boundary**. Under `CAS_PIN` the target's server-side Sprint-6 Tag-1 gate enforces the invariant (un-revoke and advance-instant writes raise `CapabilityPolicyRevocationConflict`; the replicator catches it and advances `revocation_breaches` independently from `cas_conflicts`). Under `SOURCE_WINS` the target's LWW path does NOT enforce the invariant; the replicator therefore runs an in-band `_is_revocation_breach(live, incoming)` check BEFORE the `put` call so a stale unrevoked source envelope cannot silently overwrite a revoked target record. Equal-`revoked_at`-instant rewrites are NOT a breach (so a `revocation_reason` note refresh on a revoked policy replicates cleanly). DELETE / PURGE removes a revocation lineage from the target (substrate-level hard removal; consistent with the Sprint-6 Tag-3 classifier behaviour). The cross-bucket invariant is therefore: **once a key carries a revocation on the target, no replication path will silently overwrite it.** The breach is always observable through the metrics counter; operator intervention via the Sprint-6 Tag-2 publisher-CLI `revoke` subcommand against the target bucket is always required to proceed. §6 extended with T-CPP-REP-01..14 plus 3 auxiliary probes test inventory (`wirelang/tests/test_capability_policy_replication.py` NEW, ~1100 LOC; suite 899 → 916, +17 net per the `wirelang/tests` collection at base `9c94517`): T-CPP-REP-01..05 mirror the Sprint-3 Tag-6 schema-registry-replication base path (bootstrap copy / idempotency / filter skip / live PUT / live DELETE); T-CPP-REP-06..07 mirror the CAS-conflict race-window simulation; T-CPP-REP-08..09 mirror poisoned-envelope halt and live-event filter skip; T-CPP-REP-10..11 mirror the source==target rejection and PUT-with-None-record defence-in-depth; T-CPP-REP-12 mirrors `run(bootstrap=False)`; T-CPP-REP-13 (revocation-monotonic preservation under `SOURCE_WINS`) and T-CPP-REP-14 (revocation-monotonic preservation under `CAS_PIN`) are the **Tag-6 core deliverable** asserting that a stale unrevoked source envelope is refused on the target via in-band check (T-13) or server-side gate (T-14), with the target's revoked record preserved byte-equal in both cases and `revocation_breaches` advancing independently from `cas_conflicts`. Auxiliary probes: `aux-bootstrap-revocation-breach` (bootstrap-time advance-instant refusal advances `bootstrap_revocation_breaches`), `aux-revocation-reason-refresh` (equal-instant rewrite with refreshed `revocation_reason` replicates cleanly), `aux-halt-on-revocation-breach` (`halt_on_revocation_breach=True` re-raises `CapabilityPolicyRevocationConflict` under `SOURCE_WINS` from `_apply_put` directly). The Sprint-6 Tag-6 path is **additive over Sprint-6 Tag-5 (v0.18.2)**: no existing module touched, no envelope-shape change, no schema change; the capability-policy backend (Sprint-5 Tag-2 LWW, Sprint-5 Tag-4 CAS-pin, Sprint-5 Tag-5 watch-stream, Sprint-6 Tag-1 revocation-monotonic invariant), the publisher-CLI (Sprint-3 Tag-5 / Sprint-5 Tag-1+3 / Sprint-6 Tag-2 `revoke`), the revocation-event-filter (Sprint-6 Tag-3), and the SPIFFE Workload API adapter (Sprint-6 Tag-4+5) are all byte-unchanged. The replicator is a *new module* that imports from `capability_policy_nats_kv_backend` and modifies nothing it imports; it stands alongside the Sprint-3 Tag-6 schema-registry replicator (`wirelang.schemas.replication`) as the second cross-bucket replication layer in Wirelang, with the additional invariant for capability-policy semantics. M-2 conformance preserved (no envelope-shape change; the replicator carries the same `wakir.wirelang.capability-policy-entry/1` envelope byte-precisely between source and target buckets). M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 non-touched (no Identity-Substrate touch; replication is a substrate-coordination layer, not a cryptographic primitive; the four Z-1-K-Sprint-4 consensus points remain byte-identical). Cross-Review-Zone-B non-touched (no new bucket; the existing `wakir-capability-policies` bucket configuration is byte-unchanged on both source and target sides; the replicator transports envelopes between two same-shape buckets, not a third bucket; the Z-B paired-update memo from Sprint-5 Tag-2 remains the canonical orchestrator-side action item). Cross-Review-Zone-A non-touched (the replicator is independent of any SPIFFE/SPIRE-track work; container-identity-substrate is a parallel axis). Phase-3 reservations preserved: bidirectional replication (CRDT-style merges out of scope for Sprint-6; reserved as a Phase-3 promotion slot), multi-source fan-in (operator composes multiple replicators against one target), watch-stream resume-from-revision (Phase-3 hardening item, mirror of the schema-registry reservation), capability-token enforcement on the target write (Phase-3 hardening item), token-level Biscuit v3 revocation-list propagation (Phase-3 Datalog-substrate slot; Tag-6 carries policy-level revocation, NOT token-level). Sprint-6 Tag-6+ candidates: publisher-CLI `unrevoke` subcommand (operator-deliberate unrevoke with explicit audit-trail separation; reserved as a distinct subcommand so the audit trail clearly separates revocation events from unrevoke events), real-`spiffe`-PyPI-backed `RealSpiffeWorkloadApiAdapter` (Tag-7+ paired with Kai's DevOps-track SPIRE-server integration; remains Phase-2c). Sprint-6 Tag-2 / Tag-3 follow-item "cross-bucket revocation-replication" CONSUMED. Additive-only change relative to v0.18.2. |
| 0.18.2  | 2026-05-11 | Phase-2 Sprint-6 Tag-5 lands the **test-counts convention** documentation and the **SPIFFE Workload API mock adapter** functional implementation slot for `fetch_jwt_svid`. Three additive items, additive over v0.18.1. (1) `docs/test-counts-convention.md` (NEW, ~120 LOC) reconciles the Mira-Inbox-vs-Reza-conversations test-count quote-mismatch between Sprint-6 Tag-1 ("842 → 854") and Sprint-6 Tag-3 ("868 → 885"): both numbers are correct at their respective tips; the apparent discrepancy is a baseline-pinning mismatch in the verbal report, not a CI-vs-local subtest-counting differential. The doc establishes the canonical baseline modus (local-worktree-at-tip with reza-pinned `.venv`), the three-tuple report shape (`<passed> passed, <skipped> skipped, <subtests> subtests passed`), the constant-7-subtests source (one `unittest.TestCase.subTest` block in `test_aip_https_backend.py::HappyPathTests::test_max_age_parsing_robustness` iterating over 7 cache-control cases), the per-tip verification recipe via probe-worktrees, and the §7 acceptance shape for future test-progression reports. (2) `wirelang/adapters/spiffe_workload_api.py` extended with a hermetic `MockSpiffeWorkloadApiAdapter` (in-process, no network, no FS) and `MockSvidRecord` configuration dataclass (`spiffe_id` / `token` / `extra_audiences` / `expires_at` / `unavailable` / `attestation_failed` / `permitted_audiences` fields) implementing the Sprint-6 Tag-4 Protocol surface for `fetch_jwt_svid`. The mock is deterministic (same input → byte-equal `JwtSvid` output, hashable via frozen dataclass), drives the full four-error-path semantics (`SpiffeAdapterUnavailable` / `SpiffeAdapterAttestationFailed` / `SpiffeAdapterAudienceRejected` / generic `SpiffeAdapterError` for input validation), and rejects unknown-spiffe-id lookup as attestation failure (mirroring the Workload API behaviour for an unregistered SPIFFE-ID). `fetch_x509_svid` remains stub-aligned (raises `NotImplementedError`; Phase-2c surface). `__all__` extended with the two new public names. The mock is suitable for unit tests and orchestrator integration tests that need a typed adapter without provisioning a SPIRE agent; the real upstream-`spiffe`-PyPI-backed implementation is deferred to Sprint-6 Tag-6+ / Phase-2c (paired with Kai's DevOps-track SPIRE-server integration). (3) §6 extended with `wirelang/tests/test_spiffe_workload_api_mock_adapter.py` test inventory: T-SWA-MOCK-01..03 (happy-path: default record / explicit record / explicit spiffe-id lookup), T-SWA-MOCK-04..07 (error paths: unavailable / attestation_failed / audience-rejected / unknown-spiffe-id), T-SWA-MOCK-08..09 (input validation: empty audience / empty records tuple), T-SWA-MOCK-10..12 (determinism / Protocol-conformance via `inspect.iscoroutinefunction` / x509-NotImplemented), plus 2 auxiliary probes (`__all__` resolution sanity, Protocol-vs-Mock type distinction). Suite 885 → 899 (+14 net per the `wirelang/tests` collection at base `ece8f45`). The Sprint-6 Tag-5 path is **additive over Sprint-6 Tag-4 (v0.18.1)**: no schema change, no envelope change, no existing surface touched. M-2 conformance preserved (no envelope-shape change). M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 non-touched (the mock adapter is wirelang-side surface-implementation for the Z-A surface; the four Z-1-K-Sprint-4 cryptographic-substrate consensus points remain byte-identical). Cross-Review-Zone-B non-touched (no bucket-config touch). Cross-Review-Zone-A: the mock implementation is wirelang-side surface-implementation of the Z-A-Ack 2026-05-11 wirelang-side adapter-layer indirection contract (consumes Z-A consensus markers; not new consensus). Phase-3 reservations preserved (real-`spiffe`-backed implementation deferred). Sprint-6 Tag-5+ candidates: real upstream-`spiffe`-PyPI-backed `RealSpiffeWorkloadApiAdapter` (Sprint-6 Tag-6+ / Phase-2c, paired with Kai's DevOps-track SPIRE-server integration), AIP-document-to-SPIRE-registration-entry-generator (Phase-3 wirelang-roadmap slot), per-Component-Type caveat-set enforcement in identity-document schema (Phase-2c+ Z-A follow-up), V-907 hash-algorithm migration (Phase-3, with the SPIFFE-ID 12-hex-char slice constant unchanged). Additive-only change relative to v0.18.1. |
| 0.18.1  | 2026-05-11 | Phase-2 Sprint-6 Tag-4 lands the **operator manpage** for the Sprint-6 Tag-3 consumer-side revocation-event-filter and the **SPIFFE-ID-Binding spec section** for the Z-A-Ack 2026-05-11 wirelang-side surface. Two doc-only additions, no code surface touched (additive over v0.18.0). (1) Operator manpage `docs/revocation-event-filter.md` consumes the Sprint-6 Tag-3 deferred "see operator manpage in a Tag-4 follow-up" obligation: documents `RevocationEventKind` (5 enum members), `ClassifiedRevocationEvent` (5 fields), `RevocationEventClassifier` (`__init__` / `seed_from_records` / `classify` / `known_keys` / `last_revoked_at`), `filter_revocation_events(stream, classifier=None, kinds=None)` with the full PUT/DELETE/PURGE × prior-state decision table, five worked examples (audit-log narrow filter, resume-after-restart with `seed_from_records`, BREACH-only alerting, full-audit consumer with `frozenset(RevocationEventKind)`, parallel classifier + `LiveCapabilityPolicySnapshot` drive), operational notes on default-filter rationale + DELETE/PURGE state semantics + `REVOCATION_MONOTONIC_BREACH` non-enforcement boundary + concurrency caveat, and cross-references to Tag-1 / Tag-2 / Tag-3 / Sprint-5 Tag-5 / V-907 SPIFFE-ID-Binding parallel-axis. The inline change-log entry on v0.18.0 is retained as the spec-text reference; the manpage is now the canonical operator surface. (2) `wirelang/specs/identity-substrate.md` extended with new §5 "SPIFFE-ID-Binding" (the prior §5 "Open items" becomes §6) consuming the Z-A-Ack 2026-05-11 §9 / Sprint-6 Tag-4 wirelang-side surface obligation: §5.1 SPIFFE-ID path pattern (`spiffe://<trust-domain>/agent/<persona-slug>/<persona-hash-12>` for persona-mint workloads, `spiffe://<trust-domain>/service/<service-name>` for service-only workloads); §5.2 persona-slug character class (kebab-case ASCII, same as schema-registry `registered_by` convention); §5.3 hash-algorithm-agnostic 12-hex-char display slice (hard-pin: V-907 full-form is ALWAYS `<alg>:<lower-case-hex>`, currently `sha256:<64-hex>`; SPIFFE-ID Component-3 is a 12-char display slice over the hex output after the `<alg>:` prefix is stripped; the 12-hex prefix pattern is stable across Phase-3 hash-algorithm migrations to blake3 or sha3-256); §5.4 AIP-document `issuer` URI-form compatibility (SPIFFE-ID URI is wire-compatible with the AIP `issuer` field per §2.2); §5.5 adapter-layer indirection constraint (`wirelang/adapters/spiffe_workload_api.py`; persona-container code MUST NOT import upstream `spiffe` directly; PyPI-name `spiffe` correction from Z-A-Ack §3; upstream library breaking changes are Z-A re-consensus triggers); §5.6 capability-mint surface authority per Component-Type (`/agent/` workloads can mint, `/service/` workloads only consume); §5.7 implementation cross-references (wirelang-side stub, Kai DevOps-track owner-items, Phase-3 wirelang-roadmap slots). Companion non-functional surface stub `wirelang/adapters/spiffe_workload_api.py` skeleton lands (imports + type annotations + docstring contract + `JwtSvid` frozen dataclass + `X509Svid` frozen dataclass + `SpiffeWorkloadApiAdapter` Protocol with `fetch_jwt_svid` / `fetch_x509_svid` slots + four-class error hierarchy `SpiffeAdapterError` / `SpiffeAdapterUnavailable` / `SpiffeAdapterAttestationFailed` / `SpiffeAdapterAudienceRejected`; functional implementation deferred to Sprint-6 Tag-5+ / Phase-2c, paired with Kai's SPIRE-server integration). The Sprint-6 Tag-4 path is **additive over Sprint-6 Tag-3 (v0.18.0)**: no code surface, no schema, no envelope, no test count change (885 → 885 wirelang/tests/, unchanged); the doc-only additions are surface-only. M-2 conformance preserved (no envelope-shape change). M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 non-touched (revocation-event-filter manpage is consumer-side observation surface; SPIFFE-ID-Binding spec is the wirelang-side surface for the Z-A consensus protocol — the four Z-1-K-Sprint-4 cryptographic-substrate consensus points remain byte-identical). Cross-Review-Zone-B non-touched (no new bucket). Cross-Review-Zone-A: the SPIFFE-ID-Binding spec is the wirelang-side surface consuming the Z-A-Ack 2026-05-11 consensus markers (Z-A consensus protocol acknowledgment, not new consensus). Phase-3 reservations preserved. Sprint-6 Tag-4+ candidates: full functional implementation of the adapter (deferred to Tag-5+ / Phase-2c, paired with Kai's SPIRE-track), AIP-document-to-SPIRE-registration-entry-generator (Phase-3 wirelang-roadmap slot), per-Component-Type caveat-set enforcement in identity-document schema (Phase-2c+ Z-A follow-up), V-907 hash-algorithm migration (Phase-3, with the SPIFFE-ID 12-hex-char slice constant unchanged). Additive-only change relative to v0.18.0. |
| 0.18.0  | 2026-05-11 | Phase-2 Sprint-6 Tag-3 lands the **consumer-side revocation-event-filter** path closing the Sprint-6 Tag-1 backend-write / Sprint-6 Tag-2 publisher-CLI revocation axis on the *audit-consumer* side (pattern-mirror on the Sprint-5 Tag-5 watch-stream contract): `wirelang.schemas.capability_policy_nats_kv_backend` gains `RevocationEventKind` (enum with five members: `NOT_REVOCATION_RELATED`, `REVOCATION_TRANSITION`, `REVOCATION_REFRESH`, `REVOCATION_MONOTONIC_BREACH`, `KEY_REMOVED`), `ClassifiedRevocationEvent` (frozen dataclass with `event` / `kind` / `prior_revoked_at` / `current_revoked_at` / `current_revocation_reason` fields), `RevocationEventClassifier` (stateful classifier maintaining a per-key last-observed `revoked_at` map; `__init__` / `seed_from_records(records)` for resume-after-restart bootstrap / `classify(event) -> ClassifiedRevocationEvent` with the full PUT/DELETE/PURGE x prior-state decision table / `known_keys()` / `last_revoked_at(key)`), and the async generator `filter_revocation_events(stream, classifier=None, kinds=None)` that wraps an async-iter of `CapabilityPolicyWatchEvent` and yields only the `ClassifiedRevocationEvent` instances whose `kind` is in `kinds` (default surfaces the three revocation-axis kinds — `REVOCATION_TRANSITION` + `REVOCATION_REFRESH` + `REVOCATION_MONOTONIC_BREACH` — and filters out `NOT_REVOCATION_RELATED` + `KEY_REMOVED`). `__all__` extended with the four new public names (`ClassifiedRevocationEvent`, `RevocationEventClassifier`, `RevocationEventKind`, `filter_revocation_events`). The classifier is an **observation layer, not an enforcement layer**: on observing a `REVOCATION_MONOTONIC_BREACH` (apparent un-revoke via PUT with `revoked_at=None` against a prior-revoked key, or strictly-different `revoked_at` against a prior-revoked key — both forbidden by the Sprint-6 Tag-1 backend-write invariants on the CAS-pin path) the classifier surfaces the kind and advances its state to the new value; it does NOT raise. Audit consumers decide the response (alert, halt, recovery). DELETE / PURGE events drop the key from the classifier's map (substrate-level hard removal severs the revocation lineage); a subsequent PUT for the same key is classified against fresh no-prior state (so a key re-introduced after DELETE is a `REVOCATION_TRANSITION` if it carries `revoked_at`, not a `REVOCATION_REFRESH` — the classifier preserves no revocation history beyond the event). §5.14 extended with a "Revocation-event-filter operational contract (Sprint-6 Tag-3, additive over Sprint-6 Tag-2 and Sprint-5 Tag-5)" subsection (deferred to operator manpage in a Tag-4 follow-up; the inline change-log entry is the canonical surface reference until then). §6 extended with T-CPP-REVF-01..12 + 5 auxiliary probes test inventory (`wirelang/tests/test_revocation_event_filter.py`; suite 868 → 885, +17 net per the `wirelang/tests` collection at base `3516466`). The Sprint-6 Tag-3 path is **additive over Sprint-6 Tag-2 and Sprint-5 Tag-5**: every existing surface is byte-unchanged. Backend write paths (LWW `put`, CAS-pin `put_with_revision`, Sprint-6 Tag-1 revocation-monotonicity invariant), backend read paths (`get`, `snapshot`, `snapshot_registry`), backend watch surface (`watch`, `open_capability_policy_watch_stream`, `_decode_capability_policy_watch_update`, `_CapabilityPolicyWatchStreamHandle`, `LiveCapabilityPolicySnapshot`), and the publisher-CLI `publish` / `dry-run` / `revoke` subcommands are all unaffected. The classifier and the live snapshot are **orthogonal observer objects**: a consumer can drive both `LiveCapabilityPolicySnapshot.apply(event)` (live registry axis) and `RevocationEventClassifier.classify(event)` (revocation-event axis) from the same event sequence, getting independent annotated views. `seed_from_records(records)` lets a consumer bootstrap the classifier's prior-state map from a `await backend.snapshot()` result so a post-restart watch-stream does NOT misclassify the first PUT for each pre-seeded key as a `REVOCATION_TRANSITION`. M-2 conformance preserved (no envelope-shape change; the classifier consumes the same `wakir.wirelang.capability-policy-entry/1` envelope that the watch-stream decoder produces). M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 non-touched (no Identity-Substrate touch; revocation-event classification is a consumer-side observation contract, not a cryptographic primitive or a verifier gate; the four Z-1-K-Sprint-4 consensus points remain byte-identical). Cross-Review-Zone-B non-touched (no new bucket; the `wakir-capability-policies` bucket configuration is byte-unchanged; the Sprint-5 Tag-2 Z-B paired-update memo remains the canonical orchestrator-side action item). Cross-Review-Zone-A also non-touched (the consumer-side filter is independent of any SPIFFE/SPIRE-track work; the Z-A consensus protocol for container-identity-substrate is a parallel axis). Phase-3 reservations preserved: full Biscuit v3 binary token revocation-list interpretation (Tag-3 surface is operator-policy-revocation observation, *not* token-revocation; token-level revocation lives in the Phase-3 Datalog substrate). Sprint-6 Tag-3+ candidates: operator-manpage `docs/revocation-event-filter.md` (deferred to Tag-4; the inline change-log entry is currently the canonical surface reference), cross-bucket revocation-replication (extend Sprint-3 Tag-6 replication to carry revoked policies byte-precisely so a replicated bucket's watch-stream surfaces the same classified events), publisher-CLI `unrevoke` subcommand (deliberate unrevoke with explicit audit-trail separation from accidental REVOCATION_MONOTONIC_BREACH events). Additive-only change relative to v0.17.0. |
| 0.17.0  | 2026-05-11 | Phase-2 Sprint-6 Tag-2 lands the **publisher-CLI `revoke` subcommand** composing the Sprint-6 Tag-1 capability-policy revocation backend axis onto the operator surface (`wirelang.schemas.publisher_cli`: new `revoke` subcommand with flags `--registered-by`, `--policy-id`, `--revoked-at`, `--revocation-reason`, `--registered-by-publisher`, `--registered-at`, `--expected-revision` XOR `--lww`, `--connect-url`; new `RevokeReceipt` dataclass with eleven canonical receipt fields including `cmd="revoke"`, `mode` (`"cas"` / `"lww"`), `previous_revision` / `new_revision` pair for audit-trail correlation, `expected_revision` echo; two new exit codes `ExitCode.REVOCATION_CONFLICT = 8` (Sprint-6 Tag-1 revocation-monotonic backend invariant tripped on un-revoke / advance-instant CAS-pin attempts) and `ExitCode.REVOKE_TARGET_NOT_FOUND = 9` (revoke target `(registered_by, policy_id)` does not exist on the bucket; distinct from `INPUT_ERROR` so pipelines can disambiguate "policy never existed" from "operator typo in flag"); new helpers `_add_revoke_flags`, `_run_revoke`); §5.13 extended with a "Revoke subcommand operational contract (Sprint-6 Tag-2, additive over Sprint-6 Tag-1)" subsection (deferred; see operator manpage `docs/publisher-cli-revoke.md` for the canonical surface reference); §6 extended with T-SR-REV-01..12 + 2 auxiliary probes test inventory (`wirelang/tests/test_publisher_cli_revoke.py`; suite 854 → 868, +14 net per the wirelang/tests collection). The Sprint-6 Tag-2 path is **additive over Sprint-6 Tag-1**: the existing `publish` / `dry-run` subcommands and the Sprint-5 Tag-1 / Tag-3 capability-gating flag-set are byte-unchanged in shape and surface; the `revoke` subcommand is a separate argparse subparser that touches a DIFFERENT bucket (`wakir-capability-policies` only — `wakir-schemas` is NEVER touched by the revoke path); the rewritten record preserves every non-revocation capability-bundle field byte-equal (allowed_kids / allowed_triples / disabled / note / not_before / not_after) so an operator cannot accidentally lose bundle state by revoking. CAS-pin auto-pin (no `--expected-revision`, no `--lww`) is the default safest mode: the CLI reads the live revision via `get_with_revision_by_pair` and pins the write to that revision. Operator-supplied `--expected-revision` is matched against the live revision BEFORE the backend call so a CAS conflict surfaces with `ExitCode.CAS_CONFLICT` (5) without touching the bucket. `--lww` is the explicit escape-hatch that bypasses the Sprint-6 Tag-1 revocation-monotonic backend invariant; the bucket history retains both the revocation event and the unrevoke event so the audit trail is preserved either way. M-2 conformance preserved (no envelope-shape change — the on-disk envelope is the Sprint-6 Tag-1 additive shape; the CLI is a write-path composition only). M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 non-touched (no Identity-Substrate touch; the revoke subcommand is a pure operator-CLI composition of Sprint-6 Tag-1 backend axis + the existing Sprint-3 Tag-5 publisher-CLI argparse pattern). Cross-Review-Zone-B non-touched (no new bucket; the `wakir-capability-policies` bucket configuration is byte-unchanged — the existing `history=5` audit-trail depth retains the pre-revocation envelope for audit). Phase-3 reservations preserved: full Biscuit v3 binary token revocation-list interpretation (the Sprint-6 Tag-2 surface is operator-policy-revocation, *not* token-revocation; token-level revocation lives in the Phase-3 Datalog substrate). Sprint-6 Tag-2+ candidates: watch-stream consumer-side revocation-event filter (filter on `event.record.policy.revoked_at != None`; pattern-mirror on the Sprint-5 Tag-5 watch-stream contract), cross-bucket revocation-replication (extend Sprint-3 Tag-6 replication to carry revoked policies byte-precisely), publisher-CLI `unrevoke` subcommand (operator-deliberate unrevoke via a fully-formed record write that bypasses CAS-pin; reserved as a distinct subcommand so the audit trail clearly separates revocation events from unrevoke events). Additive-only change relative to v0.16.0. |
| 0.16.0  | 2026-05-11 | Phase-2 Sprint-6 Tag-1 lands the **explicit capability-policy revocation** surface (`wirelang.schemas.registered_by_capability` gains `CapabilityPolicy.revoked_at: Optional[datetime]` and `CapabilityPolicy.revocation_reason: Optional[str]`; `DecisionSource.POLICY_REVOKED` added; gate precedence amended so a revoked policy denies categorically — outranks the Sprint-4 Tag-6 `POLICY_DISABLED` / `KID_NOT_ALLOWED` / `TRIPLE_NOT_ALLOWED` / `OUTSIDE_VALIDITY_WINDOW` fallback ordering; the revocation check denies even when `as_of=None` — deliberately stricter than the `not_before` / `not_after` window which skips on `as_of=None`); `wirelang.schemas.capability_policy_nats_kv_backend` envelope additive (`revoked_at` and `revocation_reason` keys added to the `wakir.wirelang.capability-policy-entry/1` value schema; both optional, both null-default for back-compat with Sprint-5 Tag-2..5 envelopes); new typed exception `CapabilityPolicyRevocationConflict` carrying `key` / `existing_revoked_at` / `proposed_revoked_at`; `NatsKvCapabilityPolicyBackend.put_with_revision` enforces *revocation-monotonicity* (a revoked policy MUST preserve its `revoked_at` instant byte-equally on subsequent CAS-pin writes; un-revoke and advance-instant attempts raise `CapabilityPolicyRevocationConflict`; equal-instant idempotent rewrites are permitted so `revocation_reason` refreshes remain legal); the LWW `put` path does NOT enforce monotonicity (consistent with the Sprint-5 Tag-4 rationale that LWW writes are operator-deliberate and the CAS-pin path is the safety-invariant guard); §5.12 extended with a "Revocation operational contract (Sprint-6 Tag-1, additive over Sprint-4 Tag-6 and Sprint-5 Tag-2..5)" subsection covering the bundle-shape additions, gate-precedence amendment, envelope-additive contract, CAS-pin monotonicity contract, and the LWW non-enforcement boundary; §6 extended with §6.14 T-CPP-REV-01..10 + 2 auxiliary probes test inventory (suite 842 → 854, +12 net); §5.12 boundary item "explicit revocation" CONSUMED; §7 Phase-3-Reservation "capability-policy explicit revocation slot" CONSUMED. The Sprint-6 Tag-1 path is **additive over Sprint-5 Tag-5**: Tag-2 LWW surface, Tag-3 publisher-CLI integration, Tag-4 CAS-pin surface, and Tag-5 watch-stream surface are byte-unchanged in shape; the CAS-pin write path gains the pre-CAS `Gate 3` revocation-monotonicity check that runs strictly BEFORE the underlying KV update, so a rejected revocation attempt does not advance the live revision. Verifier-side gate decisions are byte-equal regardless of registry source (full `snapshot_registry`, watch-fed `LiveCapabilityPolicySnapshot.as_registry`, or operator-local JSON file path); a revoked policy denies through all three. M-2 conformance preserved (envelope schema additive only; older Sprint-5 envelopes decode byte-equally via the additive decoder); M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 non-touched (no Identity-Substrate touch; revocation is a policy-layer authority gesture, not a cryptographic primitive; the four Z-1-K-Sprint-4 consensus points remain byte-identical). Cross-Review-Zone-B non-touched (the `wakir-capability-policies` bucket configuration is byte-unchanged — the `history=5` audit-trail depth already retains the pre-revocation envelope for audit; no new bucket; the Z-B paired-update memo from Sprint-5 Tag-2 remains the canonical orchestrator-side action item). Phase-3 reservations preserved: full Biscuit v3 binary token revocation-list interpretation (the Sprint-6 Tag-1 surface is policy-revocation, *not* token-revocation; token-level revocation lives in the Phase-3 Datalog substrate via the `wirelang/schemas/layer-3-capability-token.json` spec). Sprint-6 Tag-1+ candidates: publisher-CLI `--revoke` flag composing the CAS-pin revocation path; watch-stream consumer-side revocation-event filter (filter on `event.record.policy.revoked_at != None`); cross-bucket revocation-replication (extend Sprint-3 Tag-6 replication to carry revoked policies byte-precisely). Additive-only change relative to v0.15.0. |
| 0.15.0  | 2026-05-11 | Phase-2 Sprint-5 Tag-5 lands the **capability-policy watch-stream** path (pattern-mirror on the Phase-1b Sprint-3 Tag-4 schema-registry watch-stream contract): `wirelang.schemas.capability_policy_nats_kv_backend` gains `CapabilityPolicyWatchOp` (enum: PUT / DELETE / PURGE), `CapabilityPolicyWatchEvent` (frozen dataclass with `op` / `key` / `record` / `revision` fields; `record` is `Optional[CapabilityPolicyRecord]` — None for DELETE / PURGE), `NatsKvCapabilityPolicyBackend.watch`, top-level `open_capability_policy_watch_stream`, internal handle `_CapabilityPolicyWatchStreamHandle`, decoder `_decode_capability_policy_watch_update`, watcher-opener `_open_capability_policy_watcher`, and the live-tail consumer `LiveCapabilityPolicySnapshot` (`from_backend` / `apply` / `as_registry` / `records` / `last_revision`; internal per-key map indexed by `capability-policies/<registered_by>/<policy_id>` so deltas can update / remove a specific record). `__all__` extended with the five new public names. §5.14 extended with a "Watch-stream operational contract (Sprint-5 Tag-5, additive over Sprint-5 Tag-4)" subsection: producer-consumer pattern (long-running supervisor task feeds a `LiveCapabilityPolicySnapshot` from `watch()` and hands frozen `CapabilityPolicyRegistry` copies to the Sprint-4 Tag-6 `check_registered_by_capability` gate per verifier pass), async-iter contract (two watcher shapes — native `__aiter__` / `__anext__` and `await updates()` returning next-or-None), poison-handling (envelope errors raise `CapabilityPolicyEnvelopeError` from the iterator and terminate it; operator must drop the live view and re-bootstrap; no silent swallow), revision-monotonicity contract (`last_revision` advances monotonically; earlier-revision events do not regress), frozen-registry determinism contract for verifier passes (`as_registry()` rebuilds a `CapabilityPolicyRegistry` from a sorted-key view; the returned registry does not share storage with the live state), orthogonality to Tag-2 LWW and Tag-4 CAS-pin write paths (the watch-stream is a strict suffix of the durable bucket history; CAS-pin writes appear as one PUT event identical to LWW writes; rejected stale CAS-pin writes appear as NO event). §6 extended with §6.13 T-CPP-WS-01..10 + 2 auxiliary probes test inventory (suite 830 → 842, +12 net). §5.14 boundary item "live tail reserved as a Phase-3 slot (analogous to the schema-registry watch-stream, Sprint-3 Tag-4)" CONSUMED. §7 Phase-3-Reservation "capability-policy watch-stream slot" CONSUMED. The Sprint-5 Tag-5 path is **additive over Sprint-5 Tag-4**: the existing Tag-2 `put` / `get` / `delete` / `snapshot` / `snapshot_registry` LWW surface and the Tag-4 `put_with_revision` / `get_with_revision` / `CapabilityPolicyConflictError` CAS-pin surface are byte-unchanged. Verifier-side gate decisions are byte-equal regardless of registry source (full `snapshot_registry` or watch-fed `LiveCapabilityPolicySnapshot.as_registry`); T-CPP-WS-09 cross-references the Sprint-4 Tag-6 gate to prove byte-equal decisions. M-2 / M-4 conformance preserved (no envelope-field added, orthogonal to version axis; the watch-stream consumes the same `wakir.wirelang.capability-policy-entry/1` envelope). Cross-Review-Zone-1 non-touched (no Identity-Substrate touch; the watch-stream is a producer surface, not a verifier contract; the four Z-1-K-Sprint-4 consensus points remain byte-identical). Cross-Review-Zone-B non-touched (the `wakir-capability-policies` bucket configuration is byte-unchanged — `history=5` already exposes the watch-stream; the Z-B paired-update memo from Sprint-5 Tag-2 remains the canonical orchestrator-side action item; no new bucket). Phase-3 reservations preserved: watch-stream resumption / replay-from-revision (`watchall(..., resume_from=...)`), CAS-quorum (multi-replica CAS), Biscuit v3 binary token interpretation. Sprint-5 Tag-5+ candidate (not Tag-5): publisher-CLI composition of the live-tail consumer (a `--capability-bucket-watch` flag or daemon-mode subcommand). Additive-only change relative to v0.14.0. |
| 0.14.0  | 2026-05-11 | Phase-2 Sprint-5 Tag-4 lands the **capability-policy CAS-pin** path (pattern-mirror on the Phase-1b Sprint-3 Tag-3 schema-registry CAS-pin contract): `wirelang.schemas.capability_policy_nats_kv_backend` gains `NatsKvCapabilityPolicyBackend.get_with_revision`, `NatsKvCapabilityPolicyBackend.get_with_revision_by_pair`, `NatsKvCapabilityPolicyBackend.put_with_revision`, plus a new typed exception `CapabilityPolicyConflictError` (with `key` / `expected_revision` / `actual_revision` fields). New module-level helpers `_coerce_revision_from_entry`, `_kv_update_with_revision`, `_is_conflict_exception`, `_extract_actual_revision`, and constant `_CONFLICT_CLS_MARKERS` (byte-equal to the schema-registry CAS-pin helpers, allowing independent module evolution). §5.14 extended with a "CAS-pin operational contract (Sprint-5 Tag-4, additive over Sprint-5 Tag-2)" subsection: read-modify-write loop, validation-gate ordering (gates run BEFORE CAS, identical to Sprint-3 Tag-3 contract), KV-adapter contract (3 shapes: nats-py canonical `update(last=)`, positional fallback, `put(expected_revision=)` keyword fallback), determinism contract (3 invariants). §6.11 extended with T-CPP-CAS-01..10 + 2 auxiliary probes test inventory. §5.14 boundary item "future CAS-pinned upsert path" CONSUMED. §7 Phase-3-Reservation "capability-policy CAS-pin slot" CONSUMED. The Sprint-5 Tag-4 path is **additive over Sprint-5 Tag-2**: the existing `put` / `get` / `delete` / `snapshot` / `snapshot_registry` LWW surface is byte-unchanged, and the new CAS-pin path is the opt-in lost-update-protection surface for operators editing policies concurrently (e.g. rotating `allowed_kids` on a key-rollover; renaming `note` while preserving the validity window). The gate decision is byte-equal regardless of write path (LWW `put` or CAS `put_with_revision`). M-2 / M-4 conformance preserved (no envelope-field added, orthogonal to version axis). Cross-Review-Zone-1 non-touched (no Identity-Substrate touch; CAS-pin is a write-path concurrency contract, not a verifier contract). Cross-Review-Zone-B non-touched (the `wakir-capability-policies` bucket configuration is byte-unchanged — `history=5` already supports CAS-pin naturally; the Z-B paired-update memo from Sprint-5 Tag-2 remains the canonical orchestrator-side action item, no new bucket). Phase-2 hardening list updated: Phase-3 CAS-quorum (multi-replica CAS) remains reserved as a Phase-3 promotion slot. Additive-only change relative to v0.13.0. |
| 0.13.0  | 2026-05-11 | Phase-2 Sprint-5 Tag-3 closes the publisher-CLI capability-policy-source end-to-end (`wirelang.schemas.publisher_cli`: new flag `--capability-bucket` mutually exclusive with `--capability-registry`; new flag `--capability-bucket-connect-url` defaulting to `nats://127.0.0.1:4222`; new optional `capability_bucket_factory` injection on `run()`; new receipt field `gate_policy_source: Optional[str]` carrying `"file"` / `"bucket"` / `None`; new helper `_load_capability_registry_from_bucket`; new module-level `_default_capability_bucket_factory`; `_run_dry_run` promoted from a synchronous routine to an `asyncio.run` wrapper over `_run_dry_run_async` so the bucket factory is reachable from the dry-run path); §5.13 extended with a "Bucket policy source (Sprint-5 Tag-3)" subsection (additive over the Sprint-5 Tag-1 file-source contract); §6.10 extended with T-SR-PUB-CB-01..10 test inventory plus an auxiliary bucket-loader contract probe; §5.14 boundary item "future publisher-CLI integration slot" CONSUMED; §7 Phase-3-Reservation "publisher-CLI integration of the Sprint-5 Tag-2 persistent capability-policy backend" CONSUMED with the Sprint-5 Tag-3 flag reference. The Sprint-5 Tag-3 integration is **additive over Sprint-5 Tag-2** and additive over Sprint-5 Tag-1: the persistent-distribution tier (`NatsKvCapabilityPolicyBackend.snapshot_registry`) is invoked exactly once per CLI run if `--capability-bucket` is set, returning a Sprint-4 Tag-6 `CapabilityPolicyRegistry` that the gate consumes byte-identical to the operator-local JSON-file path. The gate decision is byte-equal regardless of source; the only receipt difference between the two sources is the `gate_policy_source` audit field. The capability-policy bucket connection is closed via the factory's cleanup callback before either the publish proceeds or the deny short-circuit fires; on a deny the schema-registry bucket is never touched (consistent with the Sprint-5 Tag-1 short-circuit contract). M-2 / M-4 conformance preserved. Cross-Review-Zone-1 non-touched (the four Z-1-K-Sprint-4 consensus points remain byte-identical; this slot is a pure operator-CLI composition of Sprint-5 Tag-2 bucket-snapshot + Sprint-4 Tag-6 gating + Sprint-5 Tag-1 sign-then-gate pipeline). Cross-Review-Zone-B non-touched (no new bucket; the Sprint-5 Tag-2 bucket `wakir-capability-policies` is consumed as-is; the Z-B paired-update memo from Sprint-5 Tag-2 remains the canonical orchestrator-side action item). Receipt-shape forward-compat: pre-Sprint-5 receipts now carry four optional fields at default-off values (`signed=false`, `kid=null`, `gate_decision=null`, `gate_policy_source=null`); consumers that index by the legacy field set continue to read byte-equal pre-existing fields. Additive-only change relative to v0.12.0. |
| 0.1.0   | 2026-05-07 | Initial draft (Phase-1b Sprint-3 Tag-1).               |
| 0.2.0   | 2026-05-07 | Phase-1c CAS-pin contract reclassified from Phase-2 to Phase-1c and lands in Tag-3 (`put_with_revision` / `get_with_revision` / `SchemaRegistryConflictError`); §5.3 Phase-1c-Slot consumed; §5.4 added. Additive-only change relative to v0.1.0; M-2 / M-4 conformance preserved. |
| 0.3.0   | 2026-05-07 | Phase-1c watch-stream surface lands in Tag-4 (`watch()` / `WatchOp` / `WatchEvent` / `LiveSchemaSnapshot` / `open_watch_stream`); §5.3 OI-7-Phase-1c-watch slot CONSUMED; §5.5 added (watch-stream operational contract); §6.2 added (T-SR-WS-01..10 + 2 aux probes test inventory). Additive-only change relative to v0.2.0; M-2 / M-4 conformance preserved. |
| 0.4.0   | 2026-05-07 | Phase-1c publisher CLI lands in Tag-5 (`wirelang.schemas.publisher_cli`: `wakir-schema-registry publish` / `dry-run` argparse surface, `PublishReceipt`, `ExitCode` matrix); §5.3 OI-7-Phase-1c-publisher slot CONSUMED; §5.6 added (publisher CLI operational contract); §6.3 added (T-SR-PUB-01..12 test inventory). Additive-only change relative to v0.3.0; M-2 / M-4 conformance preserved. The CLI is a thin operator-input layer over the Tag-3 CAS-pin and Tag-1 LWW backends; it introduces no new on-the-wire envelope and no new validation gate. |
| 0.5.0   | 2026-05-07 | Phase-1c cross-bucket replication lands in Tag-6 (`wirelang.schemas.replication`: `SchemaReplicator`, `bootstrap_target_from_source`, `ReplicationConflictPolicy`, `ReplicationFilter`, `ReplicationMetrics`); §5.3 OI-7-Phase-1c-replication slot CONSUMED; §5.7 added (replication operational contract); §6.4 added (T-SR-REP-01..12 test inventory). Additive-only change relative to v0.4.0; M-2 / M-4 conformance preserved. The replication layer is a thin composition of Tag-1 LWW + Tag-3 CAS-pin + Tag-4 watch-stream surfaces; it introduces no new on-the-wire envelope, no new validation gate, and no new method on `NatsKvSchemaRegistry`. **Phase-1c is now feature-complete.** |
| 0.12.0  | 2026-05-11 | Phase-2 Sprint-5 Tag-2 lands the persistent-distribution tier for capability policies (`wirelang.schemas.capability_policy_nats_kv_backend`: `NatsKvCapabilityPolicyBackend`, `CapabilityPolicyRecord`, `CapabilityPolicyBackendError`, `CapabilityPolicyEnvelopeError`, `CapabilityPolicyValidationError`, `BUCKET_NAME = "wakir-capability-policies"`, `BUCKET_CONFIG`, `VALUE_SCHEMA = "wakir.wirelang.capability-policy-entry/1"`, `key_for_policy_pair`, `pair_for_key`); §5.14 added (capability-policy persistent-distribution operational contract); §6.11 added (T-CPP-01..10 test inventory plus auxiliary key-derivation and envelope-shape probes); §5.12 Phase-2-Sprint-4-Tag-6-Boundary item "persistent capability-policy distribution" CONSUMED; §5.13 Sprint-5-Tag-1 boundary item "persistent capability-policy distribution" CONSUMED; §7 Phase-3-Reservierung "persistent capability-policy distribution (`wakir-capability-policies` NATS-KV bucket)" CONSUMED with the Sprint-5 Tag-2 module reference. The persistent-distribution tier is a Layer-3 substrate that mirrors the Sprint-3 Tag-1 schema-registry-backend pattern (`registry_nats_kv_backend.py`): a new dedicated NATS-KV bucket `wakir-capability-policies` keyed by `(registered_by, policy_id)` collapsed to `capability-policies/<registered_by>/<policy_id>`. The backend ships `get` / `put` / `delete` / `list_keys` / `snapshot` plus a `snapshot_registry` convenience that materialises a Sprint-4 Tag-6 `CapabilityPolicyRegistry` ready for the in-process `check_registered_by_capability` gate. Boundary: this slot does NOT replace the Sprint-5 Tag-1 `--capability-registry` operator-local JSON file format (both paths coexist; JSON-file is "policies you ship with your CLI invocation", NATS-KV is "policies you publish once for the cluster to discover"); does NOT bake CAS-pinned upserts (LWW only; Phase-3 slot mirroring Sprint-3 Tag-3); does NOT bake a watch-stream tail (full-snapshot only; Phase-3 slot mirroring Sprint-3 Tag-4); does NOT mutate `NatsKvSchemaRegistry` (the schema-registry backend is byte-unchanged); does NOT bake a publisher-CLI integration (a future `--capability-bucket` flag is a Sprint-5 Tag-3+ candidate); does NOT bake operator-side biometric / hardware key attestation on policy authorship (trust-on-write; bucket-level access control is operator-side). The on-the-wire envelope is **a new schema URI** (`wakir.wirelang.capability-policy-entry/1`) on a **new bucket** (`wakir-capability-policies`); the existing `wakir.wirelang.schema-registry-entry/1` envelope on `wakir-schemas` is byte-unchanged. M-2 conformance preserved (new envelope on new bucket; no breaking change to any existing envelope). M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 non-touched (the four Z-1-K-Sprint-4 consensus points remain byte-identical; the persistence layer is curve-agnostic, JCS-free at the policy-envelope axis, kid-resolver-independent, and orthogonal to `VerifyMode`). Cross-Review-Zone-B **TRIGGERED**: the orchestrator-side `PHASE_1_BUCKETS` inventory currently lists 6 slots (post-Sprint-4 Tag-5); Sprint-5 Tag-2 requests a 7th slot via the paired-update memo to the DevOps track (`agents-workspaces/kai/inbox/2026-05-11-reza-z-b-seventh-bucket-capability-policies-paired-update.md`). The Wirelang-side `BUCKET_CONFIG` is the byte-anchor; the orchestrator-side `BucketSpec` will mirror it on `history` / `ttl_seconds` / `max_value_size` / `storage` / `replicas` byte-precisely on Kai-side acceptance. Additive-only change relative to v0.11.0. |
| 0.11.0  | 2026-05-11 | Phase-2 Sprint-5 Tag-1 lifts the Sprint-4 Tag-6 capability gate into the publisher CLI operator surface (`wirelang.schemas.publisher_cli`: new flags `--sign`, `--kid`, `--ed25519-priv-key-hex`, `--ed25519-priv-key-file`, `--gate`, `--capability-registry`, `--gate-as-of`; new exit code `ExitCode.CAPABILITY_DENY = 7`; receipt extended with three additive optional fields `signed: bool`, `kid: Optional[str]`, `gate_decision: Optional[{allowed, source, reason}]`; helpers `_validate_capability_flag_consistency`, `_load_ed25519_priv_key`, `_load_capability_registry`, `_policy_from_dict`, `_parse_optional_rfc3339`, `_decision_to_dict`); §5.13 added (publisher-CLI capability integration operational contract); §6.10 added (T-SR-PUB-CG-01..10 test inventory, plus auxiliary loader-helper coverage); §5.3 OI-7-Phase-2-publisher-cli-capability slot CONSUMED (was the "publisher-CLI integration" Phase-3 reservation noted in §5.12 §7); §5.6 cross-references the Sprint-5 Tag-1 capability extension; §5.12 Phase-2-Sprint-4-Tag-6-Boundary item "publisher-CLI integration" CONSUMED. The Sprint-5 Tag-1 integration is **additive over Sprint-4 Tag-6**: signing reuses `wirelang.schemas.entry_signing.sign_entry` byte-identical; gating reuses `wirelang.schemas.registered_by_capability.gate_signed_entry` byte-identical; both run strictly between `_build_entry` and the backend `put` / `put_with_revision` call so the CAS-pin and LWW write paths are byte-unchanged; a `CAPABILITY_DENY` short-circuits before the backend connect (bucket never touched on deny). The capability-registry JSON file format is operator-side surface only (`{policies: [{registered_by, allowed_kids, allowed_triples, not_before?, not_after?, disabled?, note?}, ...]}`); the on-the-wire schema-registry envelope is UNCHANGED (no signature delivered to the bucket via the publisher path — Sprint-5 Tag-1 boundary: the bucket carries the unsigned entry; the signature is local-only authorisation glue, consistent with Sprint-4 Tag-6 §5.12). M-2 / M-4 conformance preserved. Cross-Review-Zone-1 non-touched (the four Z-1-K-Sprint-4 consensus points remain byte-identical; this slot is a pure operator-CLI composition of Tag-1 signing + Tag-6 gating + Tag-3/Tag-5 backend writes). Additive-only change relative to v0.10.0. Bare-publish receipt-shape forward-compat: pre-Sprint-5 receipts receive three new optional fields at default-off values (`signed=false`, `kid=null`, `gate_decision=null`); consumers that index by the legacy field set continue to read byte-equal pre-existing fields. |
| 0.10.0  | 2026-05-11 | Phase-2 Sprint-4 Tag-6 lands the `registered_by`-capability-gating layer (`wirelang.schemas.registered_by_capability`: `CapabilityPolicy`, `CapabilityPolicyRegistry`, `CapabilityGateDecision`, `DecisionSource`, `check_registered_by_capability`, `gate_signed_entry`, `RegisteredByCapabilityError`); §5.12 added (capability-gating operational contract); §6.9 added (T-RBC-01..12 test inventory). The gating layer binds the `registered_by` field of a `SchemaRegistryEntry` to a policy bundle that constrains *which* signing keys (`kid`) and *which* `(layer, name_glob)` schema triples a given publisher identity is authorised to register. The gate is **additive** authorisation on top of `wirelang.schemas.entry_signing.verify_entry_signature`: a cryptographically valid signature can still be denied if the issuer lacks capability over the registered triple. The cryptographic primitive (`verify_entry_signature`) remains the single source of truth for signature correctness and is UNCHANGED. The gate is a separate, pure-policy function returning a `CapabilityGateDecision` (`allowed: bool`, `reason: str`, `source: DecisionSource`, `policy: Optional[CapabilityPolicy]`); structural failures (malformed policy, bad arg, missing `kid` in the signature block) raise `RegisteredByCapabilityError`. Policy semantics: `allowed_kids` (set-membership), `allowed_triples` (literal `layer` plus `fnmatch` glob on `name`; layer `"*"` is the all-layers wildcard), optional RFC-3339 `not_before` / `not_after` validity window (inclusive of `not_before`, exclusive of `not_after`), `disabled` kill-switch, and free-form `note` audit string. Boundary: this slot does NOT ship full Biscuit binary token encode/decode + Datalog evaluation (those remain Phase-3 slots — see `wirelang/schemas/layer-3-capability-token.json`); does NOT mutate `NatsKvSchemaRegistry` (no new method, no envelope change, no validation gate at write time); does NOT fetch policies from a transport (in-process registry only; persisted distribution is Phase-3); does NOT touch the kid → public-key resolver (Z-1-K-Sprint-4-1 consumed upstream). Cross-Review-Zone-1 non-touched (the four Z-1-K-Sprint-4 consensus points remain byte-identical; the gate is curve-agnostic, JCS-free, resolver-independent, and orthogonal to `VerifyMode`). Additive-only change relative to v0.9.0; M-2 / M-4 conformance preserved. |
| 0.9.0   | 2026-05-11 | Phase-2 Sprint-4 Tag-5 lands the AIP-document signature-verification cache tier (`wirelang.identity.aip_signature_verification_cache`: `AipSignatureVerificationCache`, `CacheStats`, `cached_verify_aip_signature`, module-level constants `DEFAULT_MAX_ENTRIES=256`, `DEFAULT_TTL_SECONDS=300.0`); §5.11 added (verification-cache operational contract); §6.8 added (T-AIP-SVC-01..12 test inventory). The cache is a stateful in-process LRU+TTL tier on top of the Sprint-4 Tag-1 `wirelang.identity.verify_aip_signature` primitive; cache hits are byte-equal to fresh verify outcomes (the cache is a pure performance optimisation, not a behavioural layer). The cache key is `SHA-256` over the 5-tuple `(SHA-256(JCS(body without document_signature)), alg, kid, signature_hex, pub_key_hex)`, byte-identical in shape to the Sprint-4 Tag-4 `jcs_sha256_hex` byte-anchor (the cache reuses the Tag-4 ↔ Tag-1 JCS-resolver-indirection lock, Z-1-K-Sprint-4-2). Negative outcomes (`verify` returns `False`) are memoised the same way as positive outcomes; structural failures (`ValueError` from the verifier) are NOT cached and propagate verbatim. TTL defaults to 300 seconds with an injectable monotonic clock for hermetic test determinism; LRU eviction is by insertion-order (hits do NOT promote — byte-consistent with V-908 `HTTPSAipResolverCache` semantics). The cache surface is byte-orthogonal to `wirelang.identity.verify_aip_signature` (UNCHANGED), `wirelang.identity.kid_resolver` (UNCHANGED), `wirelang.identity.aip_document_transport_fetch` (UNCHANGED), and the schema-registry backend (`NatsKvSchemaRegistry` UNCHANGED, no new method). Additive-only change relative to v0.8.0; M-2 / M-4 conformance preserved. Cross-Review-Zone-1 non-touched (the four Z-1-K-Sprint-4 consensus points remain byte-identical; the cache is curve-agnostic, policy-agnostic, and resolver-independent). |
| 0.8.0   | 2026-05-11 | Phase-2 Sprint-4 Tag-4 lands the AIP-document transport-fetch composition layer (`wirelang.identity.aip_document_transport_fetch`: `fetch_aip_document`, `aip_web_to_https_url`, `AipFetchResult`, `AipDocumentTransportError`, `AipUrlSchemeError`, `AipDnsAnchorMismatchError`); §5.10 added (transport-fetch operational contract); §6.7 added (T-AIP-FT-01..12 test inventory). The module is a pure composition of the V-908 Phase-1b HTTPS-transport (`HTTPSDocumentTransport`) and the V-908 §3.4 DNS-anchor pattern, extended from FTD-doc to AIP-doc via the parallel TXT-record prefix `_wakir-aip.<host>` (same `v=1; sha256=<64-hex>` format). The transport-fetch layer is byte-orthogonal to AIP-document signature verification (`wirelang.identity.verify_aip_signature` is unchanged), the kid-resolver (Tag-3, §5.9) and the schema-registry backend (no method added to `NatsKvSchemaRegistry`); it closes the Sprint-4 Tag-3 §5.9 boundary item "AIP-document transport-fetch" so the Phase-2 canonical verifier flow is now end-to-end composable from an `aip:web:` identifier through to `verify_entry_signature`. Additive-only change relative to v0.7.0; M-2 / M-4 conformance preserved. Cross-Review-Zone-1 non-touched (the four Z-1-K-Sprint-4 consensus points remain byte-identical; `anchor_required` is an orthogonal Tag-4 hard-vs-soft toggle, not the Z-1-K-Sprint-4-4 STRICT-mode toggle). |
| 0.7.0   | 2026-05-11 | Phase-2 Sprint-4 Tag-3 lands the kid → Ed25519 public-key resolver (`wirelang.identity.kid_resolver`: `resolve_kid`, `list_resolvable_kids`, `ResolvedPublicKey`, `KidResolverError`); §5.9 added (kid-resolver operational contract); §6.6 added (T-KID-RES-01..12 test inventory); §5.8 `kid` resolution forward-reference linked. Z-1-K-Sprint-4-1 (kid-Resolver-Shape) closed by this module — `kid` matches `public_keys[i].kid` (the byte-accurate AIP-document JSON-Schema field; the Z-1-Sprint-4-Anhang consensus marker's "public_keys[i].id" wording refers to the same identifier slot). Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519) reinforced: the resolver filters out `alg == "secp256k1"` entries (those belong to the Biscuit capability-token-burst layer per the two-curve-stack consensus). The resolver does NOT fetch the AIP document over transport, does NOT validate the AIP-document signature, and does NOT mutate the schema-registry backend surface (no new method on `NatsKvSchemaRegistry`). Additive-only change relative to v0.6.0; M-2 / M-4 conformance preserved. |
| 0.6.0   | 2026-05-11 | Phase-2 entry-signing layer lands in Sprint-4 Tag-1 (`wirelang.schemas.entry_signing`: `SignedSchemaRegistryEntry`, `sign_entry`, `verify_entry_signature`, `envelope_with_signature`, `envelope_to_signed_entry`, `SchemaRegistrySignatureError`, `VerifyMode`); §5.3 OI-7-Phase-2-sig slot CONSUMED (Phase-2 hardening begins); §5.8 added (entry-signing operational contract); §6.5 added (T-SR-SIG-01..12 test inventory). Envelope schema **additive only**: optional `signature` slot on the existing `wakir.wirelang.schema-registry-entry/1` envelope (no `/2` envelope; backward-compatible with v0.5.0 readers). Tag-1 codec is unchanged; new `envelope_with_signature` / `envelope_to_signed_entry` helpers ship the round-trip for the optional slot. M-2 conformance preserved (additive-only field; absent slot is valid under permissive Phase-2-transition verify mode); M-4 conformance preserved (orthogonal to version axis). Cross-Review-Zone-1 (Identity-Substrate) **TRIGGERED**: signing reuses `wirelang.identity.aip_signing` Ed25519 + JCS + SHA-256 primitive byte-identical; the kid binds the signature to an AIP-document `public_keys` entry. `NatsKvSchemaRegistry` surface remains zero-new-method (signing happens at envelope-build time before `put` / `put_with_revision`). |

This specification defines the Wakir Wirelang **Schema Registry**: a
persistent, drift-aware store for the JSON-Schema documents that
validate Wirelang frames, AIP documents, FTD documents and the
Datalog caveat vocabulary. The registry's persistent substrate is a
single NATS-JetStream key-value bucket (`wakir-schemas`); the
registry's runtime API is a synchronous lookup contract analogous to
the V-908 `RouteRegistry` Protocol shipped in Phase-1b Sprint-2.

The registry is the natural consumer of Kai's Phase-1 NATS-KV
inventory `wakir-schemas` bucket (`scripts/init-nats-buckets.py`,
Phase-1b Sprint-2 Tag-2). Phase-1b Sprint-3 Tag-1 lands the
production-target backend wrapper; Phase-1c will land the
schema-distribution flow that publishes module-shipped schemas onto
the bucket on operator command.

## 1. Scope and motivation

### 1.1 Why a registry

Phase-1b ships seven on-disk JSON-Schema documents in
`wirelang/schemas/`:

1. `aip-document.json`               — AIP identity document
2. `datalog-caveat.json`             — Datalog caveat vocabulary
3. `federation-trust-document.json`  — V-908 FTD shape
4. `layer-0-transport.json`          — Layer 0 transport envelope
5. `layer-1-wire.json`               — Layer 1 wire frame
6. `layer-2-semantic.json`           — Layer 2 semantic frame
7. `layer-3-capability-token.json`   — Layer 3 capability-token wrap

These documents are loaded by verifier modules (e.g.
`wirelang.identity.verify_bridge`) via `importlib.resources` at
process start. The on-disk form is fine for in-process use, but it
does not scale to the Phase-2 production fleet:

- Multiple agents need the *same* schema document; without a single
  source of truth, divergence between agent containers is silent.
- Operators must roll out new schema versions atomically across
  agents; an on-disk roll-out is per-container and observably
  asynchronous.
- Audit consumers want a byte-anchorable artefact per schema; an
  on-disk file in a container image is not a stable reference.

The registry surfaces a single bucket-backed source of truth with
explicit version slots, drift detection at the test layer, and a
JCS-canonical envelope that is byte-stable for audit anchoring.

### 1.2 Phase boundaries

**Phase-1b Sprint-3 Tag-1 (this document):**

- The NATS-KV backend wrapper module.
- The on-the-wire **value envelope** schema and codec.
- The deterministic snapshot bridge (analogous to V-908
  `NatsKvRouteRegistry.snapshot`).
- 8–12 hermetic determinism tests against an in-memory mock KV.
- Bucket-config drift-test against Kai's `wakir-schemas` inventory
  entry (cross-reference test).

**Phase-1b Sprint-3 Tag-3 (additive over Tag-1):**

- The CAS-pin upsert path
  (`NatsKvSchemaRegistry.put_with_revision` /
  `get_with_revision`) — Phase-1c reclassification of the Tag-1
  Phase-2 reservation, lands here as
  **OI-7-Phase-1c-CAS** (consumed).
- The `SchemaRegistryConflictError` typed exception for lost-update
  rejection.
- 8-12 hermetic determinism tests for the CAS-pin path
  (T-SR-CAS-01..10).

**Phase-1b Sprint-3 Tag-4 (this revision, additive over Tag-3):**

- The watch-stream surface
  (`NatsKvSchemaRegistry.watch()` / `open_watch_stream` /
  `WatchOp` / `WatchEvent` / `LiveSchemaSnapshot`) — pattern-mirror
  on V-908 Tag-6 watch-stream-snapshot layer, lands here as
  **OI-7-Phase-1c-watch** (consumed).
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`)
  is UNCHANGED. The watch-stream is a *consumer* surface that feeds
  a `LiveSchemaSnapshot`; verifier passes consume frozen
  `InMemorySchemaRegistry` views taken via `as_registry()`.
- Poisoned envelopes on the stream raise
  `SchemaRegistryEnvelopeError` and terminate the iterator (no
  silent envelope poison; same contract as full snapshot).
- 8-12 hermetic determinism tests for the watch-stream path
  (T-SR-WS-01..10 + aux probes).

**Phase-1b Sprint-3 Tag-5 (this revision, additive over Tag-4):**

- The publisher CLI (`wirelang/schemas/publisher_cli.py`) exposing a
  `wakir-schema-registry` argparse surface with two subcommands:
  `publish` (operator publish flow with LWW / CAS-pin / create-only
  modes over the Tag-1 + Tag-3 backends) and `dry-run` (validate
  inputs and print the canonical receipt without touching the bucket).
- The CLI is a *thin* operator-input layer: it derives the canonical
  KV key (`schemas/<layer>/<name>/<version>`) and body-hash from
  operator input, runs two CLI-side gates (body has a non-empty
  `$id`; `--registered-by` is non-empty), then routes the entry into
  `NatsKvSchemaRegistry.put` (LWW) or `put_with_revision` (CAS / create-only).
- A stable `ExitCode` matrix (`OK=0`, `USAGE_ERROR=2`,
  `INPUT_ERROR=3`, `VALIDATION_ERROR=4`, `CAS_CONFLICT=5`,
  `BACKEND_ERROR=6`) for CI / pipeline gating.
- A canonical JSON receipt (`PublishReceipt`) on stdout for success
  and a JSON error envelope on stderr for failure; both are single
  lines of stable JSON for downstream tools.
- 12 hermetic determinism tests (T-SR-PUB-01..12) over an in-memory
  CAS-aware KV mock; the live-cluster connect path is the
  `_default_connect_factory`, which is never exercised at the test
  layer.
- This slot consumes **OI-7-Phase-1c-publisher**.

**Phase-1b Sprint-3 Tag-6 (this revision, additive over Tag-5):**

- The cross-bucket replication layer (`wirelang/schemas/replication.py`)
  exposing `SchemaReplicator` (one-way source → target replicator
  composing Tag-4 source-side watch-stream with Tag-1 / Tag-3
  target-side write paths), `bootstrap_target_from_source` (initial
  full-snapshot pass), `ReplicationConflictPolicy`
  (`SOURCE_WINS` LWW vs `CAS_PIN` CAS-pinned target writes),
  `ReplicationFilter` (curated-subset replication), and
  `ReplicationMetrics` (per-run counters surfacing bootstrap /
  live-tail / filter / conflict / envelope-error counts).
- The replicator is a *thin composition*: it adds no new method on
  `NatsKvSchemaRegistry`, no new field on `SchemaRegistryEntry`, and
  no new on-the-wire envelope. It is a separate module that consumes
  the existing Tag-1 + Tag-3 + Tag-4 surfaces.
- Tag-6 covers two production scenarios: multi-org federation (one
  upstream registry replicated into a downstream org's local cluster
  for offline lookup) and cross-cluster mirror (active-cluster →
  hot-standby tracking for fail-over readiness).
- 12 hermetic determinism tests (T-SR-REP-01..12) over the same
  in-memory CAS-aware KV mock used by Tag-3 / Tag-4 / Tag-5.
- This slot consumes **OI-7-Phase-1c-replication**. **Phase-1c is
  now feature-complete: all four Phase-1c slots (CAS, watch,
  publisher, replication) are consumed.**

**Phase-1c (out of scope, all slots now consumed):**

- ~~OI-7-Phase-1c-CAS~~ (CONSUMED in Tag-3).
- ~~OI-7-Phase-1c-watch~~ (CONSUMED in Tag-4).
- ~~OI-7-Phase-1c-publisher~~ (CONSUMED in Tag-5).
- ~~OI-7-Phase-1c-replication~~ (CONSUMED in Tag-6).

**Phase-2 Sprint-4 Tag-1 (this revision, additive over Tag-6):**

- The entry-signing layer (`wirelang/schemas/entry_signing.py`)
  exposing `SignedSchemaRegistryEntry` (wrapper dataclass for
  `SchemaRegistryEntry` + signature block), `sign_entry`,
  `verify_entry_signature`, `envelope_with_signature`,
  `envelope_to_signed_entry`, `SchemaRegistrySignatureError` (typed
  exception for malformed signature blocks), and `VerifyMode` enum
  (`PERMISSIVE` for Phase-2-transition, `STRICT` for Phase-2-end).
- The signing primitive is **Ed25519 over SHA-256 of the
  JCS-canonicalised entry envelope minus the `signature` slot** —
  byte-identical to the AIP-document signing convention
  (`wirelang.identity.aip_signing`). The signed pre-image is the
  same JSON envelope the Tag-1 codec emits, with the `signature`
  field stripped before canonicalisation.
- The envelope schema gains an **optional** `signature` slot of
  shape `{alg: "Ed25519", kid: <string>, signature: <128-hex>}`
  on the existing `wakir.wirelang.schema-registry-entry/1`
  envelope. No new envelope schema (`/2`) is introduced — v0.5.0
  readers see an unknown optional field and tolerate it. The
  Tag-1 envelope codec (`_entry_to_envelope` / `_envelope_to_entry`)
  is unchanged in Sprint-4 Tag-1; the new `envelope_with_signature`
  / `envelope_to_signed_entry` helpers in
  `wirelang.schemas.entry_signing` provide the signed round-trip
  while the Tag-1 codec stays bit-equal on unsigned envelopes.
- The `kid` references a `public_keys` entry on the registering
  agent's AIP document; the verification path resolves the kid
  to a 32-byte Ed25519 public key. Phase-2-Sprint-4 Tag-1 does
  NOT bundle a kid → key resolver (the resolver lives in
  `wirelang.identity`; the signing layer treats the public key as
  caller-supplied).
- **VerifyMode** policy:
  - `PERMISSIVE` (Phase-2-transition default): entries without a
    `signature` slot verify as `True` (legacy v0.5.0 entries pass).
  - `STRICT` (Phase-2-end): entries without a `signature` slot
    raise `SchemaRegistrySignatureError`. Phase-2-end activation
    is operator-controlled; Sprint-4 Tag-1 ships only the policy
    surface, not the activation switch.
- **`NatsKvSchemaRegistry` surface remains UNCHANGED** in Sprint-4
  Tag-1. Signing happens at envelope-build time: caller signs the
  entry, then `put` / `put_with_revision` accepts the signed
  envelope bytes opaquely (the backend transports the bytes
  unchanged through the NATS-KV layer). The backend's existing
  codec (`_entry_to_envelope` / `_envelope_to_entry`) is left
  unchanged in this slot; callers that need the round-trip with
  the optional `signature` slot use the new
  `envelope_with_signature` / `envelope_to_signed_entry` helpers
  in `wirelang.schemas.entry_signing` directly on the raw envelope
  bytes (the helpers parse and emit the same
  `wakir.wirelang.schema-registry-entry/1` envelope shape with the
  optional slot added).
- 12 hermetic determinism tests (T-SR-SIG-01..12) over Ed25519
  test vectors and the in-memory mock KV.
- This slot consumes **OI-7-Phase-2-sig**.
- **Cross-Review-Zone-1 (Identity-Substrate) TRIGGERED:** signing
  reuses the `wirelang.identity.aip_signing` JCS+SHA-256+Ed25519
  primitive byte-identical; the kid → AIP-document binding is the
  Identity-Substrate consumer touch-point. Tomás-side WAT
  Merkle-leaf builder is the natural downstream consumer of the
  signed envelope (signed envelope is byte-anchored to the WAT
  leaf via `schema_body_sha256`; the new `signature` slot extends
  the anchored byte-string). Cross-Review-Memo to Tomás recorded
  in Sprint-4 Tag-1 outbox §2.

**Phase-2 Sprint-4 Tag-3 (this revision, additive over Sprint-4 Tag-1):**

- The kid → Ed25519 public-key resolver
  (`wirelang/identity/kid_resolver.py`) exposing the pure functions
  `resolve_kid(aip_doc, kid, *, as_of=None, require_purpose=None)` and
  `list_resolvable_kids(aip_doc, *, as_of=None, require_purpose=None)`,
  the frozen dataclass `ResolvedPublicKey` (`kid` / `public_key` /
  `validafter` / `validuntil` / `purpose`), and the typed exception
  `KidResolverError`.
- The resolver lives in `wirelang.identity` (Reza-Default per
  Z-1-K-Sprint-4-1: "resolver-layer in `wirelang.identity` separat";
  the module is consumed by `wirelang.schemas.entry_signing` callers,
  not imported from it — the schema-registry module stays decoupled
  from the AIP-document trust layer).
- **Byte-accurate AIP-document field**: the resolver matches the
  caller-supplied `kid` argument against the `kid` field of each
  `public_keys` entry (the AIP-document JSON-Schema
  `wirelang/schemas/aip-document.json` defines the identifier field
  as `kid`, not `id`). The Z-1-Sprint-4-Anhang consensus marker's
  Reza-Default phrasing "public_keys[i].id" refers to the same
  identifier slot; §5.9 captures the byte-accuracy note explicitly so
  future implementations cannot drift on the field name.
- **Curve-Choice filter** per Z-1-K-Sprint-4-3 (Identity-Document-
  layer is Ed25519-only; secp256k1 entries belong to the capability-
  token-burst layer per the two-curve-stack consensus): the resolver
  filters out `alg != "Ed25519"` entries. A `kid` whose only
  matching entry is `secp256k1` raises `KidResolverError` rather than
  resolving across curves.
- **Validity-window enforcement** (caller-driven): if the caller
  supplies an `as_of` `datetime`, the resolver enforces
  `validafter <= as_of < validuntil` (open-ended `validuntil`
  treated as `+inf`). When `as_of` is omitted, no window check
  runs (historical-signature use-case). Production verifier paths
  SHOULD pass `as_of`.
- **Duplicate-kid policy**: a duplicate kid in `public_keys` is a
  structural failure of the AIP document; the resolver raises
  `KidResolverError` rather than silently selecting one entry. The
  AIP-document JSON-Schema does not forbid duplicates at write time;
  the resolver enforces single-match at read time.
- **Purpose filter**: optional `require_purpose` argument lets
  callers narrow to a purpose tag (`"biscuit-root"`,
  `"aip-signing"`, `"frame-signing"`, `"wat-anchor"`). Entries
  without a `purpose` field do not match when `require_purpose` is
  set.
- 12 hermetic determinism tests (T-KID-RES-01..12) over hand-built
  AIP-document fragments and a cross-layer test that ties the
  resolver end-to-end into `verify_entry_signature`.
- This slot closes **Z-1-K-Sprint-4-1** (kid-Resolver-Shape) and
  **Z-1-K-Sprint-4-3** (Curve-Choice reinforcement). Z-1-K-Sprint-4-2
  (JCS-Resolver-Lock) and Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-
  Owner) remain non-touched here (the resolver does not canonicalise
  and is policy-agnostic).
- **`NatsKvSchemaRegistry` surface remains UNCHANGED**. The resolver
  is a pure function over the AIP document the caller supplies; no
  backend method is added, no new envelope schema introduced, no new
  validation gate at write time. The resolver is invoked by callers
  who already hold an AIP document and a `SignedSchemaRegistryEntry`;
  they feed `resolved.public_key` into `verify_entry_signature`.
- **Boundary**: this slot does NOT fetch the AIP document over
  transport (`did:web` / `aip:web`); it does NOT validate the
  AIP-document `document_signature` (caller responsibility); it does
  NOT plumb the resolver into the schema-registry backend read path
  (verification stays caller-driven, consistent with Sprint-4 Tag-1
  Phase-2 boundary).

**Phase-2 Sprint-4 Tag-4 (this revision, additive over Sprint-4 Tag-3):**

- The AIP-document transport-fetch composition layer
  (`wirelang/identity/aip_document_transport_fetch.py`) exposing the
  pure function `fetch_aip_document(aip_id, *, transport,
  dns_resolver=None, anchor_required=False, dns_timeout_s=3.0)` and
  the URL-mapping helper `aip_web_to_https_url(aip_id) -> (url, host)`,
  the frozen dataclass `AipFetchResult` (`aip_id` / `url` / `host` /
  `aip_doc` / `body_bytes` / `jcs_sha256_hex` / `dns_anchor` /
  `anchor_matched`), and the typed exception tree
  `AipDocumentTransportError` → {`AipUrlSchemeError`,
  `AipDnsAnchorMismatchError`}.
- **URL mapping**: `aip:web:host[:port]/path` →
  `https://host[:port]/.well-known/aip/<path>.json` (RFC 8615
  well-known namespace; the `aip` subspace is the Wakir convention
  paralleling `_wakir-ftd` for FTD). A pre-resolved `https://...` URL
  passes through verbatim. Plaintext `http://` is rejected — V-908
  §3.3 is HTTPS-only end-to-end.
- **Transport delegation**: HTTPS fetch is delegated wholesale to the
  Phase-1b V-908 `HTTPSDocumentTransport` (Tag-8 PS-6 module); no
  transport invariants re-implemented at this layer. Transport-level
  failures (`HTTPSStatusError`, `HTTPSSchemeError`, etc.) propagate
  unwrapped so callers retain typed access to the V-908 §3.3
  invariants. The Tag-4 layer is therefore byte-thin over the existing
  transport.
- **DNS-anchor cross-check (Wakir-AIP variant of V-908 §3.4)**: the
  optional `dns_resolver` argument enables a TXT-record lookup at
  `_wakir-aip.<host>` returning a payload of shape
  `v=1; sha256=<64-hex>`. The format is byte-identical to V-908 §3.4's
  FTD-doc anchor; only the prefix differs (`_wakir-aip` vs
  `_wakir-ftd`). The fingerprint is compared against
  `SHA-256(JCS(body without document_signature))` computed locally
  (the same canonicalisation used by `wirelang.identity.aip_signing`).
- **Hard-vs-soft toggle**: `anchor_required` controls failure
  semantics:
  - `anchor_required=False` (default): DNS lookup is best-effort.
    Missing / malformed / mismatching TXT surfaces as `dns_anchor=None`
    or `anchor_matched=False` on the result; never raises from the
    anchor layer. The caller decides what to do.
  - `anchor_required=True`: any of {missing TXT, malformed TXT,
    fingerprint mismatch} raises `AipDnsAnchorMismatchError` with
    `expected` (the local JCS-anchor hex) and `observed` (the wire
    fingerprint hex when available) attributes. Calling with
    `dns_resolver=None` raises eagerly (the contract is unambiguous:
    requiring an anchor without a resolver is a caller bug).
- **JCS byte-anchor**: every successful fetch returns
  `result.jcs_sha256_hex` — the canonical AIP-doc fingerprint —
  computed via the same resolver-indirected JCS canonicaliser used by
  `wirelang.identity.aip_signing` (`rfc8785` when present;
  `_jcs_pure` fallback otherwise). This byte-anchor is the natural
  consumer surface for downstream WAT-leaf builders and cache tiers.
- 12 hermetic determinism tests (T-AIP-FT-01..12) over the URL
  mapping (canonical + edge-cases + rejected shapes), the HTTPS
  composition (happy path + 404 propagation + structural body
  failure), the DNS-anchor cross-check (soft-match / soft-absent /
  hard-mismatch / hard-absent), the eager-raise when
  `anchor_required=True` with `dns_resolver=None`, and the
  cross-layer composition with the Tag-3 `kid_resolver` plus a
  determinism / passthrough probe.
- This slot closes the Sprint-4 Tag-3 §5.9 boundary item
  "AIP-document transport-fetch (`did:web` / `aip:web` HTTPS bridge)
  for the kid-resolver"; the Phase-2 canonical verifier flow is now
  composable end-to-end from an `aip:web:` identifier through the
  fetch → resolve → verify chain without caller-side transport glue.
- **`NatsKvSchemaRegistry` surface remains UNCHANGED**. No backend
  method added, no new envelope schema introduced, no new validation
  gate at write time. The transport-fetch layer is orthogonal to the
  schema-registry backend; it sits at the Identity-Substrate boundary
  between the V-908 HTTPS-transport and the kid-resolver / signing
  verify path.
- **Cross-Review-Zone-1 (Identity-Substrate) non-touched**: the four
  Z-1-K-Sprint-4 consensus points remain byte-identical. The
  `anchor_required` toggle is an orthogonal Tag-4 hard-vs-soft policy,
  NOT the Z-1-K-Sprint-4-4 STRICT-mode signing toggle. JCS
  canonicalisation reuses the Z-1-K-Sprint-4-2 resolver-indirection
  byte-identical. Curve-choice is non-touched (the fetch layer is
  curve-agnostic — it fetches a document, not a key). Kid-Resolver
  surface is non-touched (the fetch layer feeds the resolver, does
  not modify its API).
- **Boundary**: this slot does NOT validate the AIP-document
  `document_signature` (caller composes with
  `wirelang.identity.verify_aip_signature`); does NOT validate the
  body against the JSON-Schema (Phase-1a `aip_resolver` ships that,
  sandbox-restricted to `rfc8785` + `jsonschema`); does NOT cache the
  result (the V-908 `HTTPSAipResolverCache` lives one layer up for
  the federation pipeline); does NOT mutate the schema-registry
  backend surface.

**Phase-2 Sprint-4 Tag-5 (this revision, additive over Sprint-4 Tag-4):**

- The AIP-document signature-verification cache tier
  (`wirelang/identity/aip_signature_verification_cache.py`) exposing
  the bounded LRU+TTL `AipSignatureVerificationCache` class
  (`__init__(*, max_entries=256, ttl_seconds=300.0, clock=time.monotonic)`,
  `verify(aip_doc, signature_block, pub_key) -> bool`, `clear()`,
  `evict_expired() -> int`, `stats` property returning a
  `CacheStats` snapshot, `max_entries` / `ttl_seconds` read-only
  properties), the frozen counter dataclass `CacheStats`
  (`hits` / `misses` / `evictions` / `expired` / `size`), the free
  function `cached_verify_aip_signature(aip_doc, signature_block,
  pub_key, *, cache)` (a one-call wrapper for type-signature
  flexibility), and the module-level constants
  `DEFAULT_MAX_ENTRIES=256` / `DEFAULT_TTL_SECONDS=300.0`.
- **Stateful tier on the stateless verifier**: the underlying
  `wirelang.identity.verify_aip_signature` (Sprint-4 Tag-1) is
  UNCHANGED. The cache calls it verbatim on miss and memoises the
  Boolean outcome. A cache hit is byte-equal to a fresh verify
  (the cache is a pure performance optimisation; callers can rely
  on hit/miss being indistinguishable in semantics).
- **Cache-key construction**: `SHA-256` over the byte-deterministic
  5-tuple
  `(SHA-256(JCS(body without document_signature)),
  alg, kid, signature_hex, pub_key_hex)` with explicit `\x00`
  separators. The 5-tuple captures every input of the underlying
  verify call; different inputs (body, alg, kid, signature hex, or
  public-key bytes) produce different cache keys; reflexive
  inputs collide. The body digest reuses the same
  resolver-indirected JCS canonicaliser used by
  `wirelang.identity.aip_signing` (Z-1-K-Sprint-4-2 JCS-Resolver-Lock
  is preserved; no new JCS path).
- **Cache-key body digest is byte-equal to the Sprint-4 Tag-4
  `jcs_sha256_hex` byte-anchor**: the cache-key construction reuses
  the same `SHA-256(JCS(body without document_signature))`
  computation as `aip_document_transport_fetch._jcs_anchor_hex`.
  Production callers that have already fetched the body via Tag-4
  pay the JCS+SHA-256 cost once: the Tag-4 transport-fetch produces
  the byte-anchor; the Tag-5 cache key reuses the same byte-anchor
  shape. The two computations are byte-equal by construction (same
  helper layer); the Tag-5 module recomputes from the body for API
  simplicity, not because of a shape difference.
- **TTL-based invalidation**: the default TTL is 300 seconds
  (`DEFAULT_TTL_SECONDS`). On lookup, an entry whose
  `(now - inserted_at) >= ttl_seconds` is dropped; the lookup falls
  through to a fresh verify and the `expired` counter increments.
  The clock is injectable via the `clock` constructor argument
  (defaults to `time.monotonic`); tests inject a controllable
  callable for hermetic determinism. TTL bounds staleness for two
  scenarios: key rotation (an AIP-document `public_keys` entry's
  `validuntil` window) and document re-publication (a re-published
  body with mutated semantics under the same JCS-anchor — unlikely
  but defence-in-depth). An out-of-band `evict_expired()` method
  walks the cache for a periodic-sweep hygiene pass.
- **LRU eviction in insertion-order**: the cache is bounded by
  `max_entries` (default 256). On an at-capacity insert, the oldest
  entry by insertion-order is evicted. A cache *hit* does NOT
  promote the entry; this matches the V-908 `HTTPSAipResolverCache`
  semantics byte-consistent across the Identity-Substrate cache
  tiers. Callers that want hit-promotion semantics should
  construct a separate cache tier.
- **Negative caching**: both `True` and `False` verify outcomes are
  cached. A bad signature (verify returns `False`) is just as
  memoisable as a good one — the cryptographic primitive is
  deterministic on `(payload, key, signature)` regardless of
  outcome. Production fleets that see retries against known-bad
  inputs (expired key rotations, replayed malicious signatures)
  benefit from the negative cache.
- **Structural failures are NOT cached**: when
  `wirelang.identity.verify_aip_signature` raises `ValueError` (a
  malformed signature block, wrong algorithm, wrong key length),
  the exception propagates verbatim and no cache entry is written.
  The cache contract: "cache stores Boolean verify outcomes;
  structural failures bubble through unchanged".
- 12 hermetic determinism tests (T-AIP-SVC-01..12) over: construction
  defaults and bad-arg validation; hit on second verify with
  outcome-equality vs. fresh verify; TTL-based invalidation with a
  fake clock; LRU eviction in insertion-order (with a hit-does-not-
  promote probe); negative caching round-trip; cache-key construction
  distinctness across all 5 components; cache-key `KeyError` on
  malformed signature_block; structural-failure non-caching;
  `evict_expired()` bulk sweep semantics; `document_signature`-slot
  stripping (the cache key is byte-equal across documents that differ
  only in the attached signature slot); `clear()` semantics
  (drops entries, preserves lifetime counters); free-function
  `cached_verify_aip_signature` wrapper byte-equivalence to the
  method form.
- This slot consumes the **AIP-document signature-verification
  cache tier** Phase-2-roadmap item (previously listed as a Phase-3
  Identity-Substrate slot in §5.3; Sprint-4 Tag-5 ships it now to
  round out the Phase-2 verifier-pipeline performance profile).
- **`NatsKvSchemaRegistry` surface remains UNCHANGED**. No backend
  method added, no new envelope schema introduced, no new
  validation gate at write time. The cache tier is orthogonal to
  the schema-registry backend; it sits at the Identity-Substrate
  layer alongside `verify_aip_signature` (Sprint-4 Tag-1) and the
  kid-resolver (Sprint-4 Tag-3) / transport-fetch (Sprint-4 Tag-4).
- **Cross-Review-Zone-1 (Identity-Substrate) non-touched**: the four
  Z-1-K-Sprint-4 consensus points remain byte-identical. The cache
  is curve-agnostic (the `alg` field is part of the cache key but
  the cache does not enforce a curve choice — Z-1-K-Sprint-4-3
  reinforced rather than touched). The cache is policy-agnostic:
  it memoises the Boolean outcome of the verifier; the caller's
  STRICT-mode policy (Sprint-4 Tag-1 `VerifyMode.STRICT`) is
  upstream and unchanged (Z-1-K-Sprint-4-4 non-touched). The cache
  does not import `kid_resolver`; it takes a `pub_key` argument
  the caller has already resolved (Z-1-K-Sprint-4-1 non-touched).
  The cache reuses the `aip_signing._jcs_canonicalize` resolver-
  indirection byte-identical for the body-digest computation
  (Z-1-K-Sprint-4-2 non-touched; no new JCS path).
- **Boundary**: this slot does NOT replace
  `wirelang.identity.verify_aip_signature` (the underlying
  verifier remains the single source of truth for cryptographic
  correctness); does NOT cache transport-fetch outputs (the V-908
  `HTTPSAipResolverCache` and the Sprint-4 Tag-4 transport-fetch
  layer are upstream and unchanged); does NOT persist across
  process boundaries (in-process only; distributed-cache contracts
  are Phase-3 slots); does NOT mutate
  `wirelang.identity.sign_aip_document` or any signing-side
  surface (Tag-5 is read-side only).

**Phase-2 Sprint-4 Tag-6 (this revision, additive over Sprint-4 Tag-5):**

- The `registered_by`-capability-gating layer
  (`wirelang/schemas/registered_by_capability.py`) exposing the
  frozen policy bundle `CapabilityPolicy`
  (`registered_by`, `allowed_kids: tuple[str, ...]`,
  `allowed_triples: tuple[tuple[str, str], ...]`,
  optional `not_before` / `not_after`, `disabled`, optional `note`),
  the in-memory `CapabilityPolicyRegistry` (`add_policy`,
  `policies_for`, `list_issuers`), the frozen decision dataclass
  `CapabilityGateDecision` (`allowed`, `reason`, `source`,
  `policy`), the `DecisionSource` enum
  (`POLICY_MATCH` / `POLICY_DISABLED` / `NO_POLICY_FOR_ISSUER` /
  `KID_NOT_ALLOWED` / `TRIPLE_NOT_ALLOWED` /
  `OUTSIDE_VALIDITY_WINDOW`), the pure gating function
  `check_registered_by_capability(entry, signature_block, registry, *, as_of=None)`,
  the composition helper
  `gate_signed_entry(signed, registry, *, as_of=None)`, and the
  typed exception `RegisteredByCapabilityError`.
- **Additive authorisation on top of cryptographic verification.**
  The gate is a *separate* policy layer; it does NOT re-verify the
  cryptographic signature, does NOT mutate
  `wirelang.schemas.entry_signing.verify_entry_signature`, and does
  NOT replace any signing-side surface. The Tag-1 signing primitive
  remains the single source of truth for signature correctness; the
  Tag-6 gate is an *additional* check that callers MUST run
  alongside cryptographic verification when capability-gating is in
  force. A cryptographically valid signature can still be denied if
  the `registered_by` identity does not hold capability over the
  schema triple it is attempting to register.
- **Policy bundle shape**: a `CapabilityPolicy` carries
  (`registered_by`, `allowed_kids`, `allowed_triples`,
  `not_before?`, `not_after?`, `disabled`, `note?`).
  `allowed_kids` is a non-empty tuple of `kid` strings the policy
  authorises; the entry's `signature_block["kid"]` MUST be a
  member. `allowed_triples` is a non-empty tuple of
  `(layer, name_glob)` pairs; the entry's `(layer, name)` MUST
  match at least one pair (layer is matched literally with `"*"`
  as wildcard; name uses `fnmatch` glob grammar — `*` / `?` /
  `[seq]`). Optional `not_before` / `not_after` define a validity
  window (inclusive of `not_before`, exclusive of `not_after`);
  `disabled=True` is a kill-switch that always denies. The
  construction-time validation raises `RegisteredByCapabilityError`
  on shape violations (empty kids/triples, inverted window,
  type mismatch).
- **Registry contract**: an in-memory `CapabilityPolicyRegistry`
  indexed by `registered_by` identity. Multiple policies per
  identity are explicitly supported (one per kid generation, one
  per schema layer); the gate iterates and short-circuits on the
  first allowing match. `policies_for` returns a defensive tuple
  snapshot; `list_issuers` returns sorted issuers. The registry is
  in-process only; persisted policy distribution (NATS-KV bucket
  `wakir-capability-policies` or analogous) is a Phase-3 slot.
- **Gate decision shape**: `CapabilityGateDecision(allowed, reason,
  source, policy)`. Frozen; equality-by-value. The `reason` is a
  free-form audit string suitable for downstream logs;
  the `source` enum lets downstream consumers distinguish *why* a
  decision was reached without parsing the string. `policy` is
  the matched policy for an allow / the attempted-but-rejected
  policy for a deny-by-policy / `None` for
  `NO_POLICY_FOR_ISSUER`.
- **Deny precedence ordering**: when no policy allows, the most-
  specific failure is recorded:
  `POLICY_DISABLED` < `KID_NOT_ALLOWED` < `TRIPLE_NOT_ALLOWED` <
  `OUTSIDE_VALIDITY_WINDOW`. A later policy's higher-precedence
  deny *replaces* an earlier lower-precedence deny in the
  recorded fallback so the audit log surfaces the most specific
  failure (e.g. a triple mismatch is more informative than a kid
  mismatch). This is structural ordering only; the iteration
  itself is FIFO over the registry's per-issuer list.
- **12 hermetic determinism tests** (T-RBC-01..12) over: construction
  defaults + bad-arg-grid (10 parametrised cases + inverted-window
  case); matching-policy allow with policy-reference roundtrip;
  unknown-issuer + empty-registry deny; kid-not-allowed deny +
  multi-policy short-circuit; layer-name triple mismatch (layer and
  name dimensions separately); layer-wildcard `"*"` + full
  `("*", "*")` wildcard; name-glob fnmatch (prefix `frame-*` and
  single-char `frame-?`); disabled-policy deny + disabled-alongside-
  enabled allow; validity-window before/after/inside + as_of-omitted
  bypass; `gate_signed_entry` end-to-end with `sign_entry`
  composition; decision dataclass immutability/equality + 7 arg-grid
  structural-failure probes on the gate-call surface;
  `CapabilityPolicyRegistry.list_issuers` + `policies_for`
  defensive-snapshot semantics + deny-precedence ordering.
- This slot consumes the **Phase-2 `registered_by`-capability-gating**
  roadmap item (mentioned as a future Phase-2 slot in spec §5.8
  boundary block since Sprint-4 Tag-1).
- **`NatsKvSchemaRegistry` surface remains UNCHANGED**. No backend
  method added, no new envelope schema introduced, no new
  validation gate at write time. The gate is a *callable*
  authorisation layer that consumers wire into their publish flow
  (e.g. the `publisher_cli` could call `gate_signed_entry` after
  `sign_entry` and before `put`, but that integration is a future
  CLI-level slot, not Tag-6 substance).
- **Cross-Review-Zone-1 (Identity-Substrate) non-touched**: the
  four Z-1-K-Sprint-4 consensus points remain byte-identical. The
  gate consumes `signature_block["kid"]` byte-equal as the caller
  supplied it and checks set-membership against `allowed_kids`; it
  does NOT call `wirelang.identity.kid_resolver.resolve_kid` (the
  kid → public-key resolution is upstream and unchanged — Z-1-K-
  Sprint-4-1 non-touched). The gate does not canonicalise anything
  (Z-1-K-Sprint-4-2 JCS-Resolver-Lock non-touched). The gate is
  curve-agnostic — it operates on the entry-signing layer which is
  Ed25519, but the gate carries no curve choice of its own (Z-1-K-
  Sprint-4-3 reinforced rather than touched). The gate is
  orthogonal to `wirelang.schemas.entry_signing.VerifyMode`
  (Z-1-K-Sprint-4-4 non-touched; the STRICT-mode-activation-owner
  question is unaffected).
- **Boundary**: this slot does NOT ship Biscuit binary token
  encode/decode + Datalog caveat evaluation (those remain Phase-3
  slots; the on-the-wire Biscuit-v3 JSON envelope schema lives at
  `wirelang/schemas/layer-3-capability-token.json` since Phase-1a
  and is referenced as the *target* shape for Phase-3 substantiation);
  does NOT distribute policies over a transport or persist them on
  a NATS-KV bucket (Phase-3); does NOT plumb gating into the
  backend write path (caller-driven; the publisher CLI integration
  is a future slot); does NOT replace
  `verify_entry_signature` (cryptographic correctness remains the
  single source of truth in `wirelang.schemas.entry_signing`); does
  NOT mutate `SignedSchemaRegistryEntry`, `sign_entry`, or any
  signing-side surface.

**Phase-2 (remaining reserved, out of scope here):**

- CAS-quorum upserts on top of multi-replica clusters
  (**OI-7-Phase-2-quorum** reserved).
- Schema-deprecation policy with overlapping-validity windows
  (**OI-7-Phase-2-deprecation** reserved).
- IPFS-anchored schema-document hashes
  (**OI-7-Phase-2-ipfs** reserved).
- Bidirectional replication with conflict-free CRDT-style merges
  (**OI-7-Phase-2-bidir-replication** reserved).
- Watch-stream resume-from-revision policy
  (**OI-7-Phase-2-resume** reserved).
- ~~AIP-document transport-fetch (`did:web` / `aip:web` HTTPS
  bridge)~~ (**CONSUMED in Sprint-4 Tag-4** by
  `wirelang.identity.aip_document_transport_fetch`; see §5.10).
- ~~AIP-document signature-verification cache tier for the
  transport-fetch layer~~ (**CONSUMED in Sprint-4 Tag-5** by
  `wirelang.identity.aip_signature_verification_cache`; see §5.11).
- STRICT-mode operator-activation toggle (Z-1-K-Sprint-4-4 remains
  open — the resolver is policy-agnostic; the toggle question is
  a Phase-2-roadmap consensus decision).

The Phase-1c slots are all consumed: Tag-3 consumed
**OI-7-Phase-1c-CAS**, Tag-4 consumed **OI-7-Phase-1c-watch**, Tag-5
consumed **OI-7-Phase-1c-publisher**, Tag-6 consumes
**OI-7-Phase-1c-replication**. Phase-2 Sprint-4 Tag-1 consumes
**OI-7-Phase-2-sig**; Sprint-4 Tag-3 closes the Z-1-Sprint-4-Anhang
follow-up `kid → public-key resolver`; Sprint-4 Tag-4 closes the
Sprint-4 Tag-3 §5.9 boundary item `AIP-document transport-fetch`;
Sprint-4 Tag-5 ships the AIP-document signature-verification cache
tier (previously listed as a Phase-3 Identity-Substrate slot) so the
Phase-2 verifier-pipeline performance profile is rounded out.
The Phase-2 reserved slots are tracked as **OI-7-Phase-2-quorum /
-deprecation / -ipfs / -bidir-replication / -resume** plus the
STRICT-toggle follow-up slot noted above.

## 2. Bucket identity (cross-reference Kai inventory)

The registry uses bucket name `wakir-schemas`, already documented in
`scripts/init-nats-buckets.py` (`PHASE_1_BUCKETS[0]`). The Phase-1b
configuration is:

| Field            | Value         | Rationale                                                  |
|------------------|---------------|------------------------------------------------------------|
| `name`           | `wakir-schemas` | Phase-1 inventory entry; do not rename.                  |
| `description`    | `"Wirelang schema registry cache (Phase-1)"` | Operator-facing.       |
| `history`        | `5`           | Audit-trail of recent overwrites; matches federation-routes. |
| `ttl_seconds`    | `0`           | Schemas have no expiry; superseded entries stay for audit. |
| `max_value_size` | `262_144` (256 KiB) | Largest current schema is ~7.3 KiB; 256 KiB headroom for v0.2 expansion. |
| `storage`        | `"file"`      | Durability for production.                                 |
| `replicas`       | `1`           | Phase-1 single-node; Phase-2 multi-node will raise.        |

**Drift contract** (identical to the V-908 backend):

The registry backend does NOT auto-create or auto-correct bucket
configuration. It expects an operator-run `init-nats-buckets` to
have established the bucket before any `NatsKvSchemaRegistry` is
constructed. A `BUCKET_CONFIG` constant in the backend module is the
single source of truth for the test-layer drift check; the
operator-side drift check lives in the orchestrator script.

**Cross-Review-Memo to Kai:** the registry adds NO new bucket to the
Phase-1 inventory (the `wakir-schemas` bucket is already in Kai's
4-bucket inventory). Kai's 5th bucket (`wakir-federation-routes`,
Tag-4 Sprint-2) is paired Z-B-update; Sprint-3 Tag-1 does NOT add a
6th bucket. The registry is a *consumer* of the existing inventory
slot; the only Kai-side acknowledgement requested is a paired-update
note in the bucket-inventory cross-reference for Tag-1's
"`wakir-schemas` is consumed by Wirelang schema-registry backend"
documentation surface.

## 3. Identity model

A registry **entry** is identified by a triple `(layer, name,
version)` collapsed into a single KV key string:

```
schemas/<layer>/<name>/<version>
```

Examples:

```
schemas/identity/aip-document/0.1.0
schemas/wire/layer-1-wire/0.1.0
schemas/wire/layer-3-capability-token/0.1.0
schemas/federation/datalog-caveat/0.2.0
schemas/federation/datalog-caveat/0.2.1
schemas/federation/federation-trust-document/0.1.0
```

The `<layer>` axis groups schemas by Wirelang concern (`identity`,
`wire`, `federation`); `<name>` is the kebab-case schema slug
matching the on-disk file basename (without `.json`); `<version>`
is the semver-like Wirelang schema version embedded in the
`$id` URI.

### 3.1 Phase-1b schema inventory (registry-side)

The Phase-1b registry recognises the following entries (the nine
slots cover the seven on-disk schemas — one of which now ships in
two consecutive vocabulary versions — plus two reserved-history
slots for `datalog-caveat` whose v0.1.0 is the Phase-1a archive
and whose v0.2.0 was the Phase-2 ratification baseline that the
Sprint-6 Tag-8 ADR-0052 patch lifts to v0.2.1):

| Layer        | Name                          | Version  | On-disk basename                       |
|--------------|-------------------------------|----------|----------------------------------------|
| `identity`   | `aip-document`                | `0.1.0`  | `aip-document.json`                    |
| `wire`       | `layer-0-transport`           | `0.1.0`  | `layer-0-transport.json`               |
| `wire`       | `layer-1-wire`                | `0.1.0`  | `layer-1-wire.json`                    |
| `wire`       | `layer-2-semantic`            | `0.1.0`  | `layer-2-semantic.json`                |
| `wire`       | `layer-3-capability-token`    | `0.1.0`  | `layer-3-capability-token.json`        |
| `federation` | `datalog-caveat`              | `0.1.0`  | (Phase-1a archive; no on-disk file in Phase-1b) |
| `federation` | `datalog-caveat`              | `0.2.0`  | (Phase-2 ratification baseline; superseded by 0.2.1 — kept in the registry key-space for forward-compat replay) |
| `federation` | `datalog-caveat`              | `0.2.1`  | `datalog-caveat.json` (ADR-0052 Class-P promotion of `caveat_hash`, Sprint-6 Tag-8) |
| `federation` | `federation-trust-document`   | `0.1.0`  | `federation-trust-document.json`       |

Nine slots total. The `datalog-caveat/0.1.0` slot is reserved (no
on-disk file ships in Phase-1b; the entry is registered to make the
versioning surface explicit and to give Phase-1c a slot for
historical replay).

### 3.2 Versioning policy

Wirelang schema versions follow the same semver-like discipline as
the wirelang spec itself (see `wirelang-spec-v0-2.md` §1.1):

- **Patch** (`x.y.Z`) — clarification, no shape change. New entry,
  same `(layer, name)`; previous patch becomes superseded but stays
  in the bucket history (`history=5`).
- **Minor** (`x.Y.0`) — additive shape change (new optional fields).
  New entry. Verifiers select the highest minor compatible with the
  frame's declared version.
- **Major** (`X.0.0`) — breaking change. New entry. Phase-1b does NOT
  perform automatic major migration; consumers select major
  explicitly.

**Phase-1b boundary:** the registry does NOT enforce schema
super-/sub-set compatibility between versions. That is a Phase-2
hardening item (OI-7-Phase-2 reserved slot).

## 4. Value envelope

Each KV entry is a JSON object with these fields:

```json
{
  "schema": "wakir.wirelang.schema-registry-entry/1",
  "layer": "<layer>",
  "name": "<name>",
  "version": "<version>",
  "schema_id": "https://wakir.dev/wirelang/schema/<name>/<version>",
  "schema_body": { ... full JSON-Schema document ... },
  "schema_body_sha256": "<hex>",
  "registered_at": "<RFC 3339 UTC>",
  "registered_by": "<role-string or aip-id>",
  "supersedes": "<key-string of previous patch entry, or null>"
}
```

Field semantics:

- `schema`: envelope schema URI fragment, fixed for Phase-1b at
  `wakir.wirelang.schema-registry-entry/1`. Drift gate; mismatched
  envelopes fail at decode.
- `layer` / `name` / `version`: identity triple, copies of the KV
  key components for self-contained reads.
- `schema_id`: the `$id` URI of the JSON-Schema document. MUST match
  the document's own `$id` field; this is verified at write time.
- `schema_body`: the full JSON-Schema document, embedded verbatim.
  Producers MUST canonicalise the body via JCS (RFC 8785) before
  embedding so the byte form is reproducible.
- `schema_body_sha256`: SHA-256 of the JCS-canonicalised
  `schema_body` bytes. Allows callers to byte-verify a fetched
  schema against an external anchor (e.g., a WAT manifest) without
  re-canonicalising.
- `registered_at`: write-time UTC timestamp.
- `registered_by`: the agent / role that wrote the entry. Phase-1b
  permits a free-form string (role-string per Brand-Guide §9 or
  AIP-id of the publishing agent); Phase-2 will tighten this to an
  AIP-id with a verified signature.
- `supersedes`: the key-string of the entry this one supersedes, or
  `null` for the first version of a `(layer, name)` pair. Allows a
  consumer to walk the supersession chain backwards.

JCS is REQUIRED for the embedded `schema_body` bytes (so the SHA-256
anchor is meaningful) but not for the envelope itself. The envelope
is stored with `sort_keys=True, separators=(",", ":")` so the bytes
are reproducible per caller; this is sufficient for in-bucket reads.

## 5. Backend API

The Phase-1b Sprint-3 Tag-1 backend module ships at
`wirelang/schemas/registry_nats_kv_backend.py`. The API mirrors the
V-908 `route_registry_nats_kv_backend` shape:

```python
@dataclass
class NatsKvSchemaRegistry:
    kv: Any
    bucket_name: str = BUCKET_NAME

    async def get(self, key: str) -> Optional[SchemaRegistryEntry]: ...
    async def get_by_triple(
        self, layer: str, name: str, version: str
    ) -> Optional[SchemaRegistryEntry]: ...
    async def get_with_revision(                         # Phase-1c (Tag-3)
        self, key: str
    ) -> Optional[tuple[SchemaRegistryEntry, int]]: ...
    async def put(self, entry: SchemaRegistryEntry) -> int: ...
    async def put_with_revision(                         # Phase-1c (Tag-3)
        self, entry: SchemaRegistryEntry, expected_revision: int
    ) -> int: ...
    async def delete(self, key: str) -> None: ...
    async def list_keys(self) -> list[str]: ...
    async def snapshot(self) -> InMemorySchemaRegistry: ...
    async def watch(self) -> _SchemaWatchStreamHandle: ...   # Phase-1c (Tag-4)
```

The Tag-4 watch-stream additions also expose:

```python
class WatchOp(enum.Enum):                                # Phase-1c (Tag-4)
    PUT = "PUT"
    DELETE = "DELETE"
    PURGE = "PURGE"

@dataclass(frozen=True)
class WatchEvent:                                        # Phase-1c (Tag-4)
    op: WatchOp
    key: str
    entry: Optional[SchemaRegistryEntry]
    revision: int

@dataclass
class LiveSchemaSnapshot:                                # Phase-1c (Tag-4)
    initial: InMemorySchemaRegistry
    last_revision: int = 0

    def apply(self, event: WatchEvent) -> None: ...
    def as_registry(self) -> InMemorySchemaRegistry: ...

    @classmethod
    async def from_backend(cls, backend) -> "LiveSchemaSnapshot": ...

async def open_watch_stream(backend) -> _SchemaWatchStreamHandle: ...
```

The `InMemorySchemaRegistry` class is a synchronous read-only view
mirroring the V-908 in-memory pattern: it exposes a `lookup(key)`
method and a `lookup_by_triple(layer, name, version)` method, both
returning `Optional[SchemaRegistryEntry]`.

### 5.1 Determinism contract

Two snapshots taken back-to-back against the same bucket state MUST
yield byte-equal `InMemorySchemaRegistry` views (entry-set is the
same; entry envelopes round-trip byte-stable through the envelope
codec). This contract is enforced by T-SR-01 / T-SR-determinism.

### 5.2 Validation gates at write

The `put` method enforces, at write time:

1. The envelope's `schema_id` field MUST equal the embedded
   `schema_body.$id` (mismatch → `SchemaRegistryEnvelopeError`).
2. The envelope's `schema_body_sha256` field MUST equal the SHA-256
   of the JCS-canonicalised `schema_body` (mismatch → error).
3. The KV key string derived from `(layer, name, version)` MUST
   match the entry's identity triple (defence in depth against
   accidental mis-keying).

These gates protect the determinism contract: a poisoned or
mis-anchored envelope cannot reach the bucket through the typed
backend.

### 5.3 What Phase-1b Sprint-3 Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 + Phase-2 Sprint-4 Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 covers, and what Phase-2 still does NOT do

**Tag-1 (v0.1.0) lands:**

- Async `get`/`put`/`delete`/`list_keys`/`snapshot` against a
  NATS-KV bucket.
- Synchronous `InMemorySchemaRegistry` view with bijective
  triple↔key derivation.
- 12 hermetic determinism tests (T-SR-01..10 + 2 aux probes).

**Tag-3 (v0.2.0) lands (additive over Tag-1):**

- Async `put_with_revision(entry, expected_revision)` for CAS-pinned
  upsert. Lost-update protection contract enforced through the
  underlying NATS-KV `update(key, value, last=expected_revision)`
  call. Conflict surfaces as `SchemaRegistryConflictError` carrying
  the observed `key`, `expected_revision`, and (when available)
  `actual_revision`.
- Async `get_with_revision(key) → Optional[(entry, revision)]` as the
  read pair: callers pass the returned revision back into
  `put_with_revision` to close the CAS loop.
- 8-12 additional hermetic determinism tests (T-SR-CAS-01..10).
- The same write-time validation gates from §5.2 run on the CAS-pin
  path BEFORE the revision-pin call. CAS does NOT relax envelope
  integrity.
- **OI-7-Phase-1c-CAS slot consumed.**

**Tag-4 (v0.3.0) lands (additive over Tag-3):**

- Async `watch() → _SchemaWatchStreamHandle` exposing decoded
  `WatchEvent` instances over the bucket. Adapter compatibility
  with two underlying watcher shapes: nats-py canonical `watchall()`
  yielding a Shape-2 watcher (`await updates()` returning next or
  None) and the alternative Shape-1 native async-iter watcher.
- `WatchOp` enum (`PUT` / `DELETE` / `PURGE`) and `WatchEvent`
  dataclass (`op` / `key` / `entry` / `revision`) carry the decoded
  operation kind, key, entry (None for DELETE/PURGE), and KV revision.
- `LiveSchemaSnapshot` keeps an in-memory copy of the registry
  (bootstrapped from `NatsKvSchemaRegistry.snapshot`), applies
  `WatchEvent` deltas via `apply()`, and hands out frozen
  `InMemorySchemaRegistry` copies via `as_registry()` for verifier
  passes. Determinism contract: a frozen copy does NOT mutate when
  subsequent watch events arrive.
- `open_watch_stream(backend)` is the entry-point; `backend.watch()`
  is the convenience wrapper.
- 8-12 additional hermetic determinism tests (T-SR-WS-01..10 + aux).
- A poisoned envelope on a `PUT` watch event raises
  `SchemaRegistryEnvelopeError` and terminates the iterator. An
  unknown `operation` kind raises the same typed error. Phase-1c
  does NOT silently swallow envelope poison on the stream.
- **OI-7-Phase-1c-watch slot consumed.**

**Tag-5 (v0.4.0) lands (additive over Tag-4):**

- The publisher CLI module `wirelang.schemas.publisher_cli` with two
  argparse subcommands:
  - `publish`: operator publish flow with three modes:
    *last-write-wins* (default; routes through `put`),
    *CAS-pin* (`--expected-revision N`; routes through
    `put_with_revision`), and *create-only* (`--create-only`,
    equivalent to `put_with_revision` with revision 0; succeeds only
    if the entry is absent on the bucket).
  - `dry-run`: validate inputs and emit the canonical receipt without
    touching the bucket.
- A stable `ExitCode` matrix (`OK=0`, `USAGE_ERROR=2`,
  `INPUT_ERROR=3`, `VALIDATION_ERROR=4`, `CAS_CONFLICT=5`,
  `BACKEND_ERROR=6`) so CI / pipeline integrators can gate on
  specific failure classes.
- A `PublishReceipt` JSON object emitted on stdout for success
  (single line, `mode` / `key` / triple / `schema_id` / `schema_body_sha256`
  / `revision` / `expected_revision` / `registered_by` /
  `registered_at` / `supersedes`); a JSON error envelope on stderr
  for failure (`error` / `exit_code` / `message`).
- 8-12 additional hermetic determinism tests (T-SR-PUB-01..12) that
  pin the parser shape, exit-code matrix, receipt schema, error
  envelope, validation gate ordering, and bucket-state invariants
  on conflict.
- A `connect_factory` injection point so tests exercise the CLI
  end-to-end against an in-memory CAS-aware KV mock without a live
  NATS cluster. The default factory wires `nats.aio.client.Client`
  plus `js.key_value(BUCKET_NAME)` for production operators.
- **OI-7-Phase-1c-publisher slot consumed.**

**Tag-6 (v0.5.0) lands (additive over Tag-5):**

- The cross-bucket replication module
  `wirelang.schemas.replication` exposing `SchemaReplicator` (one-way
  source → target replicator), `bootstrap_target_from_source` (initial
  full-snapshot pass), and the supporting types
  `ReplicationConflictPolicy`, `ReplicationDecision`,
  `ReplicationFilter`, `ReplicationMetrics`.
- Composition contract: source-side reads use Tag-4 watch-stream
  surfaces (`open_watch_stream`, `WatchEvent`, `LiveSchemaSnapshot`
  via `snapshot()` for bootstrap); target-side writes use Tag-1 LWW
  (`put`) under `SOURCE_WINS` policy or Tag-3 CAS-pin
  (`put_with_revision`) under `CAS_PIN` policy.
- Two production scenarios covered: **multi-org federation** (a
  curated subset of an upstream registry mirrored into a downstream
  org's local cluster) and **cross-cluster mirror** (active-cluster →
  hot-standby tracking for fail-over readiness).
- Bootstrap is idempotent: a re-run on a byte-equal target advances
  the `bootstrap_skipped_idempotent` counter without touching the
  bucket. Idempotency is byte-comparison via the envelope codec
  (`_entry_to_envelope(a) == _entry_to_envelope(b)`).
- 12 additional hermetic determinism tests (T-SR-REP-01..12).
- A poisoned envelope on the source watch-stream halts replication
  with `SchemaRegistryEnvelopeError`; the metrics counter
  `envelope_errors` is incremented before re-raise. The target
  state is NOT corrupted (the poisoned event never reaches the
  target write path).
- **OI-7-Phase-1c-replication slot consumed. Phase-1c is now
  feature-complete.**

**Phase-1c is feature-complete; all four Phase-1c slots are
consumed (Tag-3 / Tag-4 / Tag-5 / Tag-6).**

**Phase-2 Sprint-4 Tag-1 (v0.6.0) lands (additive over Tag-6):**

- The entry-signing module `wirelang.schemas.entry_signing` exposing
  the `SignedSchemaRegistryEntry` wrapper dataclass, the pure
  functions `sign_entry` / `verify_entry_signature`, the envelope
  helpers `envelope_with_signature` / `envelope_to_signed_entry`,
  the typed exception `SchemaRegistrySignatureError`, and the
  `VerifyMode` enum (`PERMISSIVE` / `STRICT`).
- Signing reuses the Wakir AIP-document convention byte-identical:
  Ed25519 over SHA-256 of the JCS-canonicalised envelope minus the
  `signature` slot. The `signature` block is shaped
  `{alg: "Ed25519", kid: <string>, signature: <128-hex>}` and is
  byte-equal to the AIP-document signature block.
- The on-the-wire envelope schema is **additive only**: the existing
  `wakir.wirelang.schema-registry-entry/1` value-schema gains an
  **OPTIONAL** `signature` slot. No `/2` envelope is introduced; v0.5.0
  readers tolerate the new optional field (the Tag-1 backend codec is
  extended to round-trip the slot but does NOT validate the signature
  at read time).
- The `kid` references a `public_keys` entry on the registering
  agent's AIP document; resolving the kid to a 32-byte Ed25519
  public key is the caller's responsibility (Sprint-4 Tag-1 does
  not bundle a kid → key resolver; the resolver belongs in
  `wirelang.identity`).
- Verification policy is governed by `VerifyMode`:
  - `PERMISSIVE` (Phase-2-transition default): entries WITHOUT a
    `signature` slot verify as `True` (legacy v0.5.0 entries pass);
    entries WITH a signature slot are checked end-to-end.
  - `STRICT` (Phase-2-end): entries without a `signature` slot
    raise `SchemaRegistrySignatureError`. Phase-2-end activation
    is operator-controlled; Sprint-4 Tag-1 ships the policy
    surface only, NOT the activation switch.
- 12 additional hermetic determinism tests (T-SR-SIG-01..12) over
  Ed25519 test vectors and the in-memory mock KV.
- `NatsKvSchemaRegistry` surface is UNCHANGED. Signing happens at
  envelope-build time before `put` / `put_with_revision`; the
  signed envelope flows through the existing surfaces transparently.
- **OI-7-Phase-2-sig slot consumed. Phase-2 hardening begins.**

**Phase-2 Sprint-4 Tag-3 (v0.7.0) lands (additive over Sprint-4 Tag-1):**

- The kid → Ed25519 public-key resolver module
  `wirelang.identity.kid_resolver` exposing the pure functions
  `resolve_kid` and `list_resolvable_kids`, the frozen dataclass
  `ResolvedPublicKey`, and the typed exception `KidResolverError`.
- The resolver walks `aip_doc["public_keys"]` and matches on the
  `kid` field (byte-accurate per the AIP-document JSON-Schema).
  Filters: `alg == "Ed25519"`, optional validity-window (`as_of`),
  optional `require_purpose`.
- 12 hermetic determinism tests (T-KID-RES-01..12) including a
  cross-layer test that wires `resolve_kid` end-to-end into
  `verify_entry_signature`.
- The `wirelang.schemas.entry_signing` surface is UNCHANGED in this
  slot; the resolver is consumed by callers, not invoked from within
  the signing module (Reza-Default per Z-1-K-Sprint-4-1 places the
  resolver in `wirelang.identity` and keeps schema-registry signing
  decoupled from the AIP-document trust layer).
- **Z-1-K-Sprint-4-1 (kid-Resolver-Shape) CLOSED.** Z-1-K-Sprint-4-3
  (Curve-Choice = Ed25519 for the Identity-Document layer) is
  reinforced by the resolver's alg filter.

**Phase-2 Sprint-4 Tag-4 (v0.8.0) lands (additive over Sprint-4 Tag-3):**

- The AIP-document transport-fetch composition module
  `wirelang.identity.aip_document_transport_fetch` exposing the pure
  function `fetch_aip_document(aip_id, *, transport,
  dns_resolver=None, anchor_required=False)`, the URL helper
  `aip_web_to_https_url`, the frozen dataclass `AipFetchResult`, and
  the typed exception tree `AipDocumentTransportError` → {
  `AipUrlSchemeError`, `AipDnsAnchorMismatchError` }.
- The module is a pure composition over the Phase-1b V-908
  `HTTPSDocumentTransport` (Tag-8 PS-6) and the V-908 §3.4 DNS-anchor
  pattern (`dns_anchor.fetch_anchor`); it does not re-implement any
  transport invariants and does not introduce any new envelope or
  bucket-config surface.
- URL mapping: `aip:web:host[:port]/path` →
  `https://host[:port]/.well-known/aip/<path>.json` (Wakir
  RFC-8615 well-known convention). Pre-resolved `https://...` URLs
  pass through verbatim; plaintext `http://` is rejected (V-908 §3.3).
- DNS-anchor cross-check uses a Wakir-AIP TXT record at
  `_wakir-aip.<host>` (V-908 §3.4 pattern; same `v=1; sha256=<64-hex>`
  format) compared against `SHA-256(JCS(body without
  document_signature))`. The cross-check is toggled by
  `anchor_required`; soft mode surfaces a missing/malformed/
  mismatching anchor as `dns_anchor=None` or `anchor_matched=False`;
  hard mode raises `AipDnsAnchorMismatchError`.
- 12 hermetic determinism tests (T-AIP-FT-01..12) covering URL
  mapping (canonical + edge cases + rejected shapes), transport
  composition (happy path + 404 propagation + structural body
  failure), DNS-anchor (soft-match / soft-absent / hard-mismatch /
  hard-absent), eager-raise on missing resolver, cross-layer with
  the Tag-3 `kid_resolver`, and a determinism / passthrough probe.
- This slot closes the Sprint-4 Tag-3 §5.9 boundary item
  "AIP-document transport-fetch (`did:web` / `aip:web` HTTPS
  bridge)"; the Phase-2 canonical verifier flow is now end-to-end
  composable from an `aip:web:` identifier through fetch → resolve →
  verify.
- Cross-Review-Zone-1 (Identity-Substrate) **non-touched**: the four
  Z-1-K-Sprint-4 consensus points remain byte-identical (the
  `anchor_required` toggle is an orthogonal Tag-4 hard-vs-soft
  policy, NOT the Z-1-K-Sprint-4-4 STRICT-mode signing toggle).

**Phase-2 Sprint-4 Tag-5 (v0.9.0) lands (additive over Sprint-4 Tag-4):**

- The AIP-document signature-verification cache tier
  (`wirelang.identity.aip_signature_verification_cache`: stateful
  in-process bounded LRU+TTL cache around the Sprint-4 Tag-1
  `verify_aip_signature` primitive). Hits are byte-equal to fresh
  verify outcomes; negative outcomes are memoised the same way as
  positive ones; structural failures are NOT cached.
- 12 hermetic determinism tests (T-AIP-SVC-01..12).
- `NatsKvSchemaRegistry` surface UNCHANGED; no new envelope.
- Cross-Review-Zone-1 non-touched.

**Phase-2 Sprint-4 Tag-6 (v0.10.0) lands (additive over Sprint-4 Tag-5):**

- The `registered_by`-capability-gating layer
  (`wirelang.schemas.registered_by_capability`) exposing the
  `CapabilityPolicy` policy bundle, the `CapabilityPolicyRegistry`
  in-memory registry, the `CapabilityGateDecision` frozen decision
  dataclass with a `DecisionSource` enum, the pure gating function
  `check_registered_by_capability(entry, signature_block, registry,
  *, as_of=None)`, the composition helper `gate_signed_entry`, and
  the typed exception `RegisteredByCapabilityError`.
- The gate is additive authorisation on top of
  `wirelang.schemas.entry_signing.verify_entry_signature`: a
  cryptographically valid signature can still be denied if the
  `registered_by` identity does not hold capability over the
  schema triple it is attempting to register. The cryptographic
  primitive remains the single source of truth and is UNCHANGED.
- Policy semantics: `allowed_kids` (set-membership), `allowed_triples`
  (literal `layer` plus `fnmatch` glob on `name`; layer `"*"` is the
  all-layers wildcard), optional `not_before` / `not_after` validity
  window (inclusive of `not_before`, exclusive of `not_after`),
  `disabled` kill-switch, free-form `note` audit string.
- 12 hermetic determinism tests (T-RBC-01..12) over construction
  + bad-arg-grid + matching policy + unknown issuer + kid-not-
  allowed + triple-not-allowed (layer/name) + layer wildcard +
  name fnmatch glob (prefix + ?-single) + disabled-policy + validity
  window (before/after/inside/as_of-omitted) + `gate_signed_entry`
  composition with `sign_entry` + decision dataclass shape and 7
  structural arg-grid probes + registry list/lookup defensive-
  snapshot + deny-precedence ordering.
- This slot consumes the **Phase-2 `registered_by`-capability-gating**
  roadmap item (mentioned as a future Phase-2 slot in §5.8
  boundary block since Sprint-4 Tag-1).
- `NatsKvSchemaRegistry` surface UNCHANGED; no new envelope, no
  new validation gate at write time; the gate is a callable
  authorisation layer that consumers wire into their publish flow
  (~~publisher-CLI integration is a future slot~~ — **CONSUMED in
  Sprint-5 Tag-1**, §5.13: `wakir-schema-registry publish
  --sign --gate --capability-registry <path>` ships the
  operator-CLI projection of the canonical capability-gated
  publish flow).
- Cross-Review-Zone-1 non-touched (the four Z-1-K-Sprint-4 consensus
  points remain byte-identical; the gate is curve-agnostic,
  JCS-free, resolver-independent, and orthogonal to
  `VerifyMode`).

**Phase-2 still does NOT include:**

- No CAS-quorum upserts on top of multi-replica clusters (Tag-3
  CAS-pin assumes the operator's `replicas: 1` Phase-1 setup; the
  contract holds bit-equally on a multi-replica bucket but is not
  exercised at the test layer).
- No deprecation policy (`OI-7-Phase-2-deprecation` reserved).
- No IPFS-anchored schema hashes (`OI-7-Phase-2-ipfs` reserved).
- No bidirectional replication (`OI-7-Phase-2-bidir-replication`
  reserved).
- No watch-stream resume-from-revision policy
  (`OI-7-Phase-2-resume` reserved).
- ~~No kid → public-key resolver in the signing layer~~
  (**CONSUMED in Sprint-4 Tag-3** by
  `wirelang.identity.kid_resolver`; see §5.9).
- No automatic signature verification on the backend read path
  (verification stays caller-driven; backend codec is pass-through
  for the optional slot).
- ~~No AIP-document transport-fetch (`did:web` / `aip:web` HTTPS
  bridge) — the kid-resolver assumes the caller has already fetched
  the AIP document; transport-fetch is a separate Identity-Substrate
  slot.~~ (**CONSUMED in Sprint-4 Tag-4** by
  `wirelang.identity.aip_document_transport_fetch`; see §5.10.)
- ~~No AIP-document signature-verification cache tier (the Tag-4
  transport-fetch is stateless; production callers compose with
  the V-908 `HTTPSAipResolverCache` or an outer cache tier).
  Phase-3 Identity-Substrate slot.~~ (**CONSUMED in Sprint-4 Tag-5**
  by `wirelang.identity.aip_signature_verification_cache`; see
  §5.11.)
- ~~No `registered_by`-capability-gating on schema-registry entries
  (the Tag-1 entry-signing layer accepts any free-form
  `registered_by`; capability binding to issuer policy is a
  follow-up Phase-2 slot).~~ (**CONSUMED in Sprint-4 Tag-6** by
  `wirelang.schemas.registered_by_capability`; see §5.12.)
- No Biscuit binary token encode/decode + Datalog caveat
  evaluation (the Sprint-4 Tag-6 gate is in-process policy bundle;
  full Biscuit-v3 machinery on top of
  `wirelang/schemas/layer-3-capability-token.json` remains a
  Phase-3 slot).
- ~~No persistent capability-policy distribution (the Sprint-4 Tag-6
  registry is in-process only; persisted distribution over NATS-KV
  or analogous is a Phase-3 slot).~~ (**CONSUMED in Sprint-5 Tag-2**
  by `wirelang.schemas.capability_policy_nats_kv_backend`; see §5.14.
  The persistent-distribution tier ships the `wakir-capability-policies`
  NATS-KV bucket with `NatsKvCapabilityPolicyBackend.put` / `get` /
  `delete` / `snapshot` / `snapshot_registry`, where `snapshot_registry`
  materialises a Sprint-4 Tag-6 `CapabilityPolicyRegistry` directly
  consumable by `check_registered_by_capability`. The in-process
  registry from §5.12 remains the canonical evaluation tier; this
  slot is its persistent-distribution back-end.)
- ~~No publisher-CLI integration of the Sprint-4 Tag-6 gate (the
  capability check is caller-driven; a `wakir-schema-registry
  publish` flag that runs `gate_signed_entry` between `sign_entry`
  and `put` is a future slot).~~ **CONSUMED in Sprint-5 Tag-1**
  (§5.13). The publisher CLI now ships `--sign --kid
  --ed25519-priv-key-{hex,file}` for the signing primitive and
  `--gate --capability-registry [--gate-as-of]` for the gate.
  Exit-code 7 (`CAPABILITY_DENY`) is reserved for the deny path;
  the bucket is never touched on a deny.
- No STRICT-mode activation toggle (Z-1-K-Sprint-4-4 still open;
  the resolver is policy-agnostic).

### 5.4 CAS-pin operational contract (Tag-3)

The CAS-pin contract is the canonical compare-and-swap idiom.

**Read-modify-write loop:**

```python
read = await registry.get_with_revision("schemas/wire/layer-1-wire/0.1.0")
if read is None:
    raise NotFoundError(...)
entry, observed_revision = read

new_body = mutate(entry.schema_body)
new_entry = SchemaRegistryEntry(
    layer=entry.layer,
    name=entry.name,
    version=entry.version,
    schema_id=entry.schema_id,
    schema_body=new_body,
    schema_body_sha256=schema_body_sha256(new_body),
    registered_at=now_utc(),
    registered_by=entry.registered_by,
    supersedes=entry.supersedes,
)

try:
    new_revision = await registry.put_with_revision(
        new_entry, observed_revision
    )
except SchemaRegistryConflictError as exc:
    # Re-read and retry; or surface to the operator.
    ...
```

**Validation gate ordering (REQUIRED):**

1. Envelope `schema_id ↔ schema_body.$id` (gate 1, §5.2 / Tag-1).
2. Envelope `schema_body_sha256` ↔ recomputed JCS-anchored hash
   (gate 2, §5.2 / Tag-1).
3. Triple-derived key matches the entry (gate 3, §5.2 / Tag-1).
4. NATS-KV `update(key, value, last=expected_revision)` call;
   raises a backend-specific `KeyWrongLastSequenceError` if the live
   revision has advanced. The Tag-3 backend translates that into
   `SchemaRegistryConflictError`.

Gates 1-3 run BEFORE gate 4 so a malformed envelope cannot poison
the bucket even if the revision happened to be stale. Gate 4 runs
LAST so the network call only happens for envelopes that have
already passed integrity checks.

**KV adapter contract:**

The backend supports three KV adapter shapes (mock-friendliness):

- `kv.update(key, value, last=revision)` — canonical nats-py shape
  (KeyValue.update; raises KeyWrongLastSequenceError on conflict).
- `kv.update(key, value, expected_revision)` — positional fallback
  for mocks that don't accept the `last` keyword.
- `kv.put(key, value, expected_revision=...)` — keyword fallback for
  mocks that overload `put`.

Conflict detection is class-name-based: any exception whose class
name carries one of `WrongLastSequence` / `Conflict` /
`RevisionMismatch` is translated into
`SchemaRegistryConflictError`. This matches nats-py 2.x as well as
the orchestrator-side mock JetStream surface.

**Determinism contract (Tag-3 invariant):**

- Successful CAS-pin on the same `(key, expected_revision)` from two
  different callers: exactly one succeeds; the other receives a
  `SchemaRegistryConflictError`. The accepted writer's revision is
  monotonically greater than `expected_revision`.
- Any sequence of CAS-pins that all observe consistent revisions
  composes into a deterministic bucket state regardless of operator
  interleaving.
- A `SchemaRegistryConflictError` is **never** raised AFTER the
  envelope-integrity gates fail; the envelope-integrity gates run
  first and raise their own typed errors.

### 5.5 Watch-stream operational contract (Tag-4)

The watch-stream contract is the canonical incremental-view idiom for
long-running supervisors. It mirrors the V-908 Tag-6 watch-stream
pattern shipped in `wirelang/federation/route_registry_nats_kv_backend.py`.

**Bootstrap-and-apply loop:**

```python
backend = NatsKvSchemaRegistry(kv=kv_handle)

# 1. Take a full snapshot to bootstrap the in-memory view.
live = await LiveSchemaSnapshot.from_backend(backend)

# 2. Open the watch-stream and apply incoming events.
async with await backend.watch() as stream:
    async for event in stream:
        live.apply(event)
        if some_external_trigger:
            # Hand a frozen view to a verifier pass.
            frozen = live.as_registry()
            verify_with_registry(frozen)
```

**Event kinds:**

- `WatchOp.PUT`: a new or updated schema entry. The `WatchEvent.entry`
  field carries the decoded `SchemaRegistryEntry`. `LiveSchemaSnapshot.apply`
  inserts or replaces the entry.
- `WatchOp.DELETE`: an explicit tombstone on the bucket key. The
  `WatchEvent.entry` field is `None`. `LiveSchemaSnapshot.apply`
  removes the key from the live state (no-op if already absent).
- `WatchOp.PURGE`: a history-clearing purge on the key. Treated
  identically to DELETE for live-state purposes; surfaced separately
  so audit consumers can distinguish a purge from a tombstone.

**Adapter contract:**

The backend supports three watcher adapter shapes:

- nats-py canonical: `await kv.watchall()` returning a Shape-2 watcher
  (`await updates()` yielding next or `None` for end-of-stream).
- Shape-1 fallback: a native async-iter watcher (`__aiter__` /
  `__anext__`) raising `StopAsyncIteration` at end-of-stream.
- nats-py end-of-initial-replay sentinel (`None` between snapshot
  replay and live tail) is filtered out at the handle layer; consumers
  do NOT see it.

**Decoder contract (REQUIRED gate ordering on each event):**

1. Read `operation` attribute (or `Mapping["operation"]`); reject
   missing / unknown values with `SchemaRegistryEnvelopeError`.
2. Read `key` attribute (or `Mapping["key"]`); reject empty /
   non-string keys with `SchemaRegistryEnvelopeError`.
3. Read `revision` attribute (or `Mapping["revision"]`); coerce to
   `int` (default `0` if missing).
4. For `PUT`: decode `value` bytes through `_envelope_to_entry`
   (re-runs the Tag-1 envelope codec gates; a poisoned envelope
   surfaces `SchemaRegistryEnvelopeError`). For `DELETE` / `PURGE`:
   `entry` is `None`, no value-decode.

**Determinism contract (Tag-4 invariant):**

- A frozen `InMemorySchemaRegistry` returned from
  `LiveSchemaSnapshot.as_registry` does NOT mutate when subsequent
  `apply()` calls arrive. Verifier passes that hold a frozen view
  observe a stable point-in-time snapshot.
- `LiveSchemaSnapshot.last_revision` advances monotonically: an
  event with a revision lower than the current `last_revision` does
  NOT regress the counter (out-of-order or duplicate events do not
  corrupt the high-water mark).
- A poisoned envelope on a `PUT` event raises
  `SchemaRegistryEnvelopeError` from the iterator; the consumer must
  drop the `LiveSchemaSnapshot` and re-bootstrap from a fresh
  `NatsKvSchemaRegistry.snapshot`. Phase-1c does NOT attempt
  partial-recovery on the stream.

**Phase-1c boundary:**

- The watch-stream is a *consumer* surface; it does NOT replace
  `snapshot()`. Verifier passes always consume frozen
  `InMemorySchemaRegistry` views; the watch-stream is the *producer*
  of those views, not a new verifier substrate.
- Watch-stream resume-from-revision is a Phase-2 concern; the Tag-4
  wrapper exposes `WatchEvent.revision` so callers can implement
  resume policies on top, but the wrapper itself does not bake in
  any resume contract.
- Multi-watch federation (one supervisor watching multiple buckets,
  e.g. routes + schemas) is an integrator concern; each backend
  exposes its own `watch()` and the integrator composes them.

### 5.6 Publisher CLI operational contract (Tag-5)

The publisher CLI is the canonical operator-input layer onto the
`wakir-schemas` bucket. It is a thin shell: every gate the CLI
applies is either an operator-input shape gate (so a malformed
JSON file is rejected at the file-read layer) or a routing decision
into the existing Tag-1 / Tag-3 backend gates.

**Subcommand surface:**

```text
wakir-schema-registry publish    \
    --schema-body PATH            \
    --layer {identity,wire,federation}  \
    --name NAME                   \
    --version VERSION             \
    --registered-by ACTOR         \
    [--registered-at RFC3339Z]    \
    [--supersedes SCHEMA_ID]      \
    [(--expected-revision N | --create-only)]  \
    [--connect-url URL]

wakir-schema-registry dry-run    \
    --schema-body PATH            \
    --layer {identity,wire,federation}  \
    --name NAME                   \
    --version VERSION             \
    --registered-by ACTOR         \
    [--registered-at RFC3339Z]    \
    [--supersedes SCHEMA_ID]
```

**Mode resolution:**

- No CAS flag → mode `lww`; routes through `NatsKvSchemaRegistry.put`.
- `--expected-revision N` (N ≥ 0) → mode `cas`; routes through
  `NatsKvSchemaRegistry.put_with_revision(entry, expected_revision=N)`.
- `--create-only` → mode `create-only`; routes through
  `put_with_revision(entry, expected_revision=0)`. Succeeds only if
  the entry is absent.
- `--expected-revision` and `--create-only` are mutually exclusive
  at the argparse layer (USAGE_ERROR / exit 2).

**Subject-mapping pattern (mirror of V-908 NATS-subject mapping):**

The CLI mirrors the V-908 federation NATS-subject-to-route_id
convention applied at the operator-input layer: the user supplies
the canonical identity triple (`--layer / --name / --version`) plus
a schema-body file. The CLI derives:

- The canonical KV key (`schemas/<layer>/<name>/<version>`) via
  `key_for_triple`; identity-triple validation runs eagerly so a
  malformed triple cannot reach the bucket.
- The canonical body-hash (`schema_body_sha256(body)` over JCS-canonical
  bytes) as the entry's `schema_body_sha256` field.
- The entry's `schema_id` from `body['$id']`; the backend's gate 1
  (`schema_id ↔ schema_body.$id`) therefore always matches by
  construction. The CLI does NOT permit operator-supplied
  `schema_id` overrides; the body is the canonical source.

There is no intermediate "subject" namespace; the triple is the
subject and the key derivation is the mapping. Mirror principle
preserved without introducing a parallel namespace.

**Gate ordering (REQUIRED):**

1. argparse parse → USAGE_ERROR (exit 2) for bad flag combinations.
2. File read of `--schema-body` → INPUT_ERROR (exit 3) for missing
   file, permission error, non-UTF-8 bytes, malformed JSON, or
   non-object root.
3. CLI-side validation gates → VALIDATION_ERROR (exit 4):
   - `schema_body['$id']` is a non-empty string.
   - `--registered-by` is a non-empty string after whitespace strip.
4. Identity-triple key derivation (`key_for_triple`) → INPUT_ERROR
   (exit 3) on a malformed triple component (this surfaces as
   `ValueError`).
5. Backend write gates (only on `publish`):
   - Tag-1 gates 1-3 (`schema_id ↔ $id`, body-hash match, key↔triple
     match) → VALIDATION_ERROR (exit 4).
   - Tag-3 CAS-pin call (only for `cas` and `create-only` modes) →
     CAS_CONFLICT (exit 5) on a `SchemaRegistryConflictError`.
   - Any other backend / transport exception → BACKEND_ERROR (exit 6).
6. Receipt emission on stdout for success; exit 0.

Gates 1-4 run BEFORE any NATS connect; on `dry-run`, gate 5 is
skipped entirely. The CLI is therefore safe to gate a CI pipeline:
a `dry-run` that returns OK guarantees that a subsequent `publish`
will not fail at gates 1-4.

**Receipt schema (success on stdout, single JSON line):**

```json
{
  "mode": "lww" | "cas" | "create-only" | "dry-run",
  "key": "schemas/<layer>/<name>/<version>",
  "layer": "<layer>",
  "name": "<name>",
  "version": "<version>",
  "schema_id": "<schema-body $id>",
  "schema_body_sha256": "<hex digest>",
  "revision": <int> | null,
  "expected_revision": <int> | null,
  "registered_by": "<actor>",
  "registered_at": "<RFC 3339 UTC>",
  "supersedes": "<schema_id>" | null
}
```

`revision` is the new live KV revision after a successful publish;
`null` for `dry-run`. `expected_revision` echoes the operator's
input (or 0 for `create-only`, `null` for LWW / dry-run).

**Error envelope (failure on stderr, single JSON line):**

```json
{
  "error": "<ExitCode name>",
  "exit_code": <int>,
  "message": "<human-readable message>"
}
```

`exit_code` matches the process exit status; `error` is one of
`USAGE_ERROR` / `INPUT_ERROR` / `VALIDATION_ERROR` / `CAS_CONFLICT` /
`BACKEND_ERROR`.

**Determinism contract (Tag-5 invariant):**

- Stdout and stderr are disjoint per invocation. On success, stderr
  is empty; on failure, stdout is empty.
- A failed publish (any non-OK exit code) leaves the bucket state
  byte-equal to the pre-call state. CAS conflicts are observable but
  non-mutating; validation errors abort BEFORE the network call;
  input errors abort BEFORE entry construction.
- Two identical `dry-run` invocations on the same `--schema-body`
  file produce byte-equal receipts (modulo `registered_at` if the
  operator omits the override flag). Test paths supply
  `--registered-at` explicitly so the receipt is byte-stable.

**Phase-1c boundary:**

- The publisher CLI is a *write-side* surface; it does NOT consume
  the watch-stream and does NOT post-verify the publish through the
  Tag-4 watch surface. Operators who want post-publish observability
  compose the CLI with a separate `LiveSchemaSnapshot` consumer (see
  §5.5).
- Multi-replica rollout sequencing is an integrator concern; the
  CLI publishes one entry per invocation.
- Authentication / capability enforcement is not in scope for
  Phase-1c; the CLI runs with whatever NATS credentials the
  operator's environment provides. ~~Capability-token enforcement at
  the publisher boundary is an OI-7-Phase-2-sig hardening item.~~
  **CONSUMED in Sprint-5 Tag-1** (§5.13). The CLI now exposes
  `--sign` (with `--kid` and an Ed25519 key source) plus `--gate`
  (with `--capability-registry`) flags; both are off by default
  (pre-Sprint-5 behaviour is byte-equal under no flags). The
  capability deny path exits with code 7 (`CAPABILITY_DENY`); the
  Sprint-5 Tag-1 receipt adds three optional fields (`signed`,
  `kid`, `gate_decision`) that default to `false` / `null` / `null`
  when the capability flags are absent.

### 5.7 Replication operational contract (Tag-6)

The replication layer is the canonical one-way (source → target)
mirror substrate for the `wakir-schemas` bucket. It is a thin
composition of three Phase-1c surfaces (Tag-1 LWW, Tag-3 CAS-pin,
Tag-4 watch-stream); the replicator itself adds no new method on
`NatsKvSchemaRegistry`, no new envelope field, and no new
validation gate.

**Composition contract:**

- **Source side (Tag-4):** the replicator opens a watch-stream over
  the source backend via `open_watch_stream(source)` and consumes
  decoded `WatchEvent` instances. Bootstrap is taken from
  `source.snapshot()` so the target starts from a complete,
  self-consistent view; the watch-stream then fills in the live tail.
- **Target side (Tag-3 CAS-pin or Tag-1 LWW):** writes go through
  `target.put` (under `SOURCE_WINS`) or
  `target.put_with_revision` (under `CAS_PIN`), depending on the
  configured `ReplicationConflictPolicy`.
- **Operator-input side (Tag-5):** the publisher CLI is the
  *separate* operator-driven write path; an operator can use it
  against the target bucket to forcibly re-apply a divergent entry
  from the source. The replicator does NOT itself bake an
  operator-override into the event loop.

**Conflict policy:**

```python
class ReplicationConflictPolicy(enum.Enum):
    SOURCE_WINS = "source-wins"  # target.put (LWW)
    CAS_PIN     = "cas-pin"      # target.put_with_revision
```

- `SOURCE_WINS` (default): source-of-truth is the source bucket;
  whatever the source emits lands on the target unconditionally.
  Concurrent target-side mutations are silently overwritten on the
  next source emit.
- `CAS_PIN`: target writes carry the target's currently-observed
  revision (read via `target.get_with_revision` just before the
  write). A target-side concurrent mutation between the read and
  the write surfaces as `SchemaRegistryConflictError` from the
  underlying backend; the replicator catches it, increments
  `metrics.cas_conflicts`, and continues with the next event by
  default. `halt_on_conflict=True` re-raises on first conflict.

**Filter contract:**

```python
ReplicationFilter = Callable[[WatchEvent], ReplicationDecision]

class ReplicationDecision(enum.Enum):
    APPLY = "apply"
    SKIP  = "skip"
```

The optional `filter_fn` is invoked on every observed event
(bootstrap synthetic events and live tail events alike). A `SKIP`
decision means the event is NOT applied to the target; the relevant
`*_skipped_by_filter` counter advances. Filters are pure (no I/O)
by contract.

**Metrics contract:**

```python
@dataclass
class ReplicationMetrics:
    bootstrap_applied: int
    bootstrap_skipped_by_filter: int
    bootstrap_skipped_idempotent: int
    events_applied_put: int
    events_applied_delete: int
    events_skipped_by_filter: int
    cas_conflicts: int
    envelope_errors: int
```

The replicator updates these counters synchronously inside its
event loop. Tests assert against the final shape; production
operators expose them via a metrics-pull endpoint (out of scope
for Tag-6).

**Bootstrap idempotency:**

`bootstrap_target_from_source` is byte-comparison-idempotent: if the
target already holds an entry that round-trips to the same envelope
bytes as the source-side entry (`_entry_to_envelope(a) ==
_entry_to_envelope(b)`), the bootstrap pass treats it as a no-op
(`bootstrap_skipped_idempotent` counter advances). Re-running the
bootstrap on a partially-replicated target is therefore safe.

Bootstrap ordering: source entries are written in `keys_sorted()`
order (lexicographic) for log-replay determinism in tests; nats-py
KV does not guarantee cross-key ordering anyway.

**Run loop:**

```python
replicator = SchemaReplicator(
    source=source_backend,
    target=target_backend,
    conflict_policy=ReplicationConflictPolicy.SOURCE_WINS,
    filter_fn=only_wire_layer,  # optional
)
metrics = await replicator.run()  # bootstrap + watch-tail
```

By default, `run()` runs the bootstrap pass then opens the source
watch-stream and consumes events until the stream terminates.
`run(bootstrap=False)` skips the bootstrap pass for callers that
have already seeded the target.

**Halt policy:**

- `halt_on_envelope_error` (default `True`): a poisoned source
  watch-stream event terminates `run` with a re-raised
  `SchemaRegistryEnvelopeError`. The metrics counter
  `envelope_errors` is incremented to 1 before re-raise.
- `halt_on_conflict` (default `False`): under `CAS_PIN`, a target
  CAS conflict terminates `run` with a re-raised
  `SchemaRegistryConflictError`. The metrics counter
  `cas_conflicts` is incremented before re-raise.

**Determinism contract (Tag-6 invariants):**

1. A bootstrap-only run leaves the target's keysets byte-equal to
   the source's keysets (modulo entries filtered out). Re-running
   the bootstrap on the same source state is a no-op for entries
   already byte-equal on the target.
2. A poisoned envelope on the source watch-stream raises
   `SchemaRegistryEnvelopeError` from the run loop and terminates
   replication. The target state is NOT corrupted because the
   poisoned event never reaches the target write path.
3. A target-side CAS conflict (under `CAS_PIN`) is observable
   through `metrics.cas_conflicts`; the replicator continues with
   the next event by default.
4. Source==target is rejected at construction with `ValueError`
   (no self-replication; the constructor enforces distinct backend
   instances).

**Phase-1c boundary:**

- Tag-6 is **one-way**: source → target. Bidirectional replication
  with conflict-free CRDT-style merges is `OI-7-Phase-2-bidir-replication`
  reserved.
- Tag-6 is **single-source / single-target** per replicator. Multi-source
  fan-in is achieved by running multiple `SchemaReplicator` instances
  against one target backend.
- Tag-6 has **no resume-from-revision policy**: a connection drop
  forces a full bootstrap-and-tail restart. Resume policies are
  `OI-7-Phase-2-resume` reserved.
- Tag-6 has **no envelope-side capability-token enforcement**; the
  replicator inherits whatever NATS credentials the operator's
  environment provides on each backend. Capability-token enforcement
  at the replication boundary is `OI-7-Phase-2-sig` reserved.

### 5.8 Entry-signing operational contract (Phase-2 Sprint-4 Tag-1)

The entry-signing layer is the canonical Ed25519 signature substrate
for schema-registry entries. It is a thin composition over the Tag-1
envelope codec and the existing `wirelang.identity.aip_signing`
JCS + SHA-256 + Ed25519 primitive; it adds no new method on
`NatsKvSchemaRegistry`, no new validation gate at the backend write
path, and no new envelope schema URI (the existing
`wakir.wirelang.schema-registry-entry/1` envelope gains an OPTIONAL
`signature` slot only).

**Signing primitive (byte-identical to AIP-document signing):**

1. **Strip** the `signature` slot from a deep copy of the envelope
   payload. The signature value cannot be part of its own pre-image.
2. **Canonicalise** with RFC 8785 JCS (resolver indirection: `rfc8785`
   when importable, the pure-Python fallback in
   `wirelang.identity._jcs_pure` otherwise; the two paths produce
   byte-identical output for the registry-entry envelope shape).
3. **Hash** with SHA-256 of the JCS bytes; sign the digest with
   Ed25519. Verification runs the same procedure in reverse.

**Signature block shape:**

```json
{
  "alg": "Ed25519",
  "kid": "biscuit-root-1",
  "signature": "<128-hex-char Ed25519 signature>"
}
```

`alg` is fixed at `"Ed25519"` in v0.6.0; other algorithms are
out of scope. `kid` references an AIP-document `public_keys` entry
identifier (caller-supplied; the registry layer does NOT resolve
kids to public keys). `signature` is the lowercase hex of the
64-byte Ed25519 signature.

**Wrapper dataclass:**

```python
@dataclass(frozen=True)
class SignedSchemaRegistryEntry:
    entry: SchemaRegistryEntry
    signature: Mapping[str, Any]  # signature block, frozen at construct time
```

A `SignedSchemaRegistryEntry` is the in-memory pair of a Tag-1
`SchemaRegistryEntry` and its detached signature block. The signature
block is stored on the envelope under the optional `signature` slot;
the wrapper makes the in-memory representation explicit.

**Public API:**

```python
def sign_entry(
    entry: SchemaRegistryEntry,
    ed25519_priv_key: bytes,
    *,
    kid: str,
) -> SignedSchemaRegistryEntry: ...

def verify_entry_signature(
    signed: SignedSchemaRegistryEntry | SchemaRegistryEntry,
    ed25519_pub_key: bytes | None = None,
    *,
    mode: VerifyMode = VerifyMode.PERMISSIVE,
    signature_block: Optional[Mapping[str, Any]] = None,
) -> bool: ...

def envelope_with_signature(
    signed: SignedSchemaRegistryEntry,
) -> bytes: ...

def envelope_to_signed_entry(
    blob: bytes,
) -> SignedSchemaRegistryEntry | SchemaRegistryEntry: ...
```

`envelope_with_signature` emits the canonical envelope bytes
(`wakir.wirelang.schema-registry-entry/1`) with the optional
`signature` slot populated. `envelope_to_signed_entry` is its inverse:
when the envelope carries a `signature` slot, it returns
`SignedSchemaRegistryEntry`; otherwise it returns the unsigned
`SchemaRegistryEntry` (parity with the Tag-1 codec).

**Verify-mode policy:**

```python
class VerifyMode(enum.Enum):
    PERMISSIVE = "permissive"  # Phase-2 transition default
    STRICT     = "strict"      # Phase-2 end
```

- `PERMISSIVE`: an unsigned entry (no `signature` slot, or a
  `SchemaRegistryEntry` passed to `verify_entry_signature` without
  a `signature_block` argument) verifies as `True`. A signed entry
  is verified end-to-end; a tampered signature raises
  `SchemaRegistrySignatureError` for structural failures and returns
  `False` for cryptographic failures.
- `STRICT`: an unsigned entry raises `SchemaRegistrySignatureError`
  with a missing-signature message. Phase-2-end activation is
  operator-controlled (out of scope for Sprint-4 Tag-1).

**Typed exception:**

`SchemaRegistrySignatureError` is the structural-failure error
class. It is raised on: missing `signature` slot under `STRICT`
mode, missing `alg` / `kid` / `signature` fields in the signature
block, unsupported `alg`, malformed signature hex, wrong signature
length, and wrong public-key length. A *cryptographic* mismatch
(valid structure, signature does not verify) returns `False` from
`verify_entry_signature`. The distinction matches the AIP-document
signing convention.

**Determinism contract (Phase-2 Sprint-4 Tag-1 invariants):**

1. **Byte-identical pre-image:** for any two `SchemaRegistryEntry`
   instances `a` and `b` such that `_entry_to_envelope(a) ==
   _entry_to_envelope(b)`, the SHA-256 of the JCS-canonicalised
   envelope-minus-signature is byte-identical. Signing is therefore
   deterministic with respect to entry content.
2. **Self-reference exclusion:** the `signature` slot is removed
   from the pre-image before canonicalisation. A signature can
   never sign over itself.
3. **Optional-slot backward compatibility:** envelopes WITHOUT a
   `signature` slot round-trip through the Tag-1 codec unchanged.
   v0.5.0 readers see v0.6.0 unsigned envelopes as byte-equal.
4. **Signature block schema rigidity:** the signature block MUST
   carry `alg == "Ed25519"`, a non-empty `kid`, and a 128-hex-char
   `signature`. Any deviation raises
   `SchemaRegistrySignatureError`. The block is the same shape as
   the AIP-document `document_signature` block.

**Cross-Review-Zone-1 (Identity-Substrate) touch:**

- The signing primitive is byte-identical to
  `wirelang.identity.aip_signing` (Ed25519 + JCS + SHA-256). The
  schema-registry signing module re-uses the same JCS resolver
  indirection (`rfc8785` with pure-Python fallback) for surface
  consistency.
- The `kid` field is a free-form string in Sprint-4 Tag-1; binding
  it to an AIP-document `public_keys` entry is the kid → key
  resolver's responsibility (out of scope for this slot). Cross-
  Review-Memo to Tomás (WAT-side) is recorded in Sprint-4 Tag-1
  outbox §2.

**Phase-2 Sprint-4 Tag-1 boundary:**

- Sprint-4 Tag-1 ships the signing primitive and verify-mode policy;
  it does NOT ship the kid → key resolver.
- Sprint-4 Tag-1 does NOT plumb signature verification into the
  backend read path; verification is caller-driven.
- Sprint-4 Tag-1 ships the `STRICT` mode policy surface but NOT
  the activation switch (operator-controlled toggle is a future
  Phase-2 slot).
- ~~Capability-token gating on `registered_by` (mapping `kid` to
  an issuer-policy bundle) is reserved for a follow-up Phase-2
  slot; the current `registered_by` field stays free-form.~~
  (**CONSUMED in Sprint-4 Tag-6** by
  `wirelang.schemas.registered_by_capability`; see §5.12 for the
  capability-gating operational contract. The `registered_by`
  field shape itself remains free-form; the Tag-6 layer is an
  additive authorisation tier that runs alongside the Tag-1
  cryptographic primitive.)
- The Tag-1 backend codec is extended to round-trip the optional
  `signature` slot; it does NOT validate the signature at read
  time (consistent with the design that verification is a separate
  caller-driven step).

**Forward reference (Sprint-4 Tag-3):** the `kid` referenced in
`signature.kid` is resolved to a 32-byte Ed25519 public key by
`wirelang.identity.kid_resolver.resolve_kid(aip_doc, kid)`. See §5.9
for the resolver operational contract.

### 5.9 kid-resolver operational contract (Phase-2 Sprint-4 Tag-3)

The kid-resolver layer binds the free-form `kid` string carried on a
signature block (§5.8) to a concrete 32-byte raw Ed25519 public key
read from an AIP document. It is a pure function in
`wirelang.identity.kid_resolver`; it does NOT mutate the
schema-registry backend, does NOT add a method to
`NatsKvSchemaRegistry`, and does NOT introduce a new envelope schema.

**Module location and rationale:**

The resolver lives in `wirelang.identity`, not in
`wirelang.schemas.entry_signing`. This placement reflects the
Z-1-K-Sprint-4-1 consensus marker default ("resolver-layer in
`wirelang.identity` separat"): the schema-registry signing module
treats the public key as caller-supplied, and the AIP-document trust
layer is the natural home for the kid → key binding. Callers compose
the two modules: read an AIP document, call `resolve_kid`, feed the
resolved public key into `verify_entry_signature`.

**Byte-accurate AIP-document field**

The Reza-Default phrasing in the Z-1-Sprint-4-Anhang consensus marker
("`kid` matched AIP-doc `public_keys[i].id` string") refers to the
identifier slot on each `public_keys` entry. The AIP-document JSON
Schema (`wirelang/schemas/aip-document.json` v0.1.0) defines this
field as `kid`, not `id`. The resolver matches on the `kid` field
byte-accurately; the consensus marker's `id` wording was a colloquial
reference to "the identifier" and is reconciled here by this byte-
accuracy note. Future implementations MUST match on `kid` to stay
schema-compliant.

**Public API:**

```python
@dataclass(frozen=True)
class ResolvedPublicKey:
    kid: str
    public_key: bytes                # 32-byte raw Ed25519
    validafter: Optional[datetime]
    validuntil: Optional[datetime]
    purpose: Optional[str]

def resolve_kid(
    aip_doc: Mapping[str, Any],
    kid: str,
    *,
    as_of: Optional[datetime] = None,
    require_purpose: Optional[str] = None,
) -> ResolvedPublicKey: ...

def list_resolvable_kids(
    aip_doc: Mapping[str, Any],
    *,
    as_of: Optional[datetime] = None,
    require_purpose: Optional[str] = None,
) -> list[str]: ...

class KidResolverError(Exception): ...
```

**Resolver filters (in order of application):**

1. **Required field** `aip_doc["public_keys"]` is a non-empty
   sequence of mappings; `kid` is a non-empty string. Violations
   raise `KidResolverError`.
2. **Kid match**: linear scan over `public_keys`, matching on
   `entry["kid"] == kid`. Zero matches → `kid not found`.
   ≥ 2 matches → `duplicate kid` (structural failure of the AIP
   document; the resolver refuses to silently pick a winner).
3. **Algorithm filter (Z-1-K-Sprint-4-3 reinforcement)**: the
   matched entry MUST have `alg == "Ed25519"`. A `secp256k1` entry
   raises `KidResolverError` — those keys belong to the Biscuit
   capability-token-burst layer (two-curve-stack consensus).
4. **Key-length validation**: `key_hex` MUST be a 64-char lowercase
   hex string decoding to 32 raw bytes.
5. **Validity-window enforcement (caller-driven)**: when `as_of` is
   supplied, the resolver enforces
   `validafter <= as_of < validuntil`. Open-ended `validuntil`
   (`None` or `null`) is treated as `+infinity`. Naive `as_of`
   datetimes are promoted to UTC. Production verifier paths SHOULD
   pass `as_of` to bind signatures to a point in time.
6. **Purpose filter (caller-driven)**: when `require_purpose` is
   supplied, the matched entry MUST have a `purpose` field byte-
   equal to the argument. Entries without a `purpose` field do not
   match. Default: no purpose filter.

**Determinism contract (Phase-2 Sprint-4 Tag-3 invariants):**

1. **Pure function**: `resolve_kid` does not mutate its input
   `aip_doc`. The frozen `ResolvedPublicKey` is the only output.
2. **Reproducible**: repeated calls on a byte-equal `aip_doc` and
   the same arguments produce equal `ResolvedPublicKey` instances
   (frozen-dataclass equality).
3. **Structural-vs-cryptographic split**: structural failures of
   the AIP document raise `KidResolverError`. A successfully-
   resolved key may still fail signature verification downstream —
   that crypto-failure surfaces as `False` from
   `verify_entry_signature`, not as `KidResolverError`. The split
   matches the entry-signing module's exception convention.
4. **Order-deterministic `list_resolvable_kids`**: returns a sorted
   list. Repeated calls produce byte-equal lists.

**Cross-Review-Zone-1 (Identity-Substrate) closure:**

- **Z-1-K-Sprint-4-1 (kid-Resolver-Shape) CLOSED** by this module.
- **Z-1-K-Sprint-4-3 (Curve-Choice for Schema-Registry-Sigs)
  reinforced**: `alg == "Ed25519"` filter enforced. The resolver
  cannot bridge from a secp256k1 entry to the Identity-Document
  signing layer.
- **Z-1-K-Sprint-4-2 (JCS-Resolver-Lock) non-touched**: the
  resolver does not canonicalise — it is a pure structural read.
- **Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner) non-touched**:
  the resolver is policy-agnostic. The caller drives `VerifyMode`
  and decides when to require resolution.

**Phase-2 Sprint-4 Tag-3 boundary:**

- The resolver does NOT fetch the AIP document over transport
  (`did:web` / `aip:web` HTTPS bridge). Transport-fetch lives in a
  follow-up Identity-Substrate slot.
- The resolver does NOT validate the AIP-document
  `document_signature` slot. Establishing AIP-document trust is the
  caller's responsibility — `wirelang.identity.verify_aip_signature`
  is the natural companion.
- The resolver does NOT plumb into the schema-registry backend read
  path. Verification stays caller-driven (consistent with Sprint-4
  Tag-1 entry-signing boundary).
- The resolver does NOT bind `kid` to the schema-registry
  `registered_by` field. Capability-token gating on `registered_by`
  remains a future Phase-2 slot.

**Composition pattern (canonical end-to-end verifier flow):**

```python
# 1. Fetch and (caller-side) trust the AIP document.
aip_doc = fetch_aip_document_for(entry.registered_by)  # caller path

# 2. Resolve the signing kid to a public key.
from wirelang.identity import resolve_kid
resolved = resolve_kid(
    aip_doc,
    signed.signature["kid"],
    as_of=now_utc(),
    require_purpose="aip-signing",  # optional narrowing
)

# 3. Verify the schema-registry-entry signature end-to-end.
from wirelang.schemas.entry_signing import verify_entry_signature, VerifyMode
ok = verify_entry_signature(
    signed, resolved.public_key, mode=VerifyMode.STRICT,
)
```

This composition is the recommended Phase-2 verifier pattern.
Sprint-4 Tag-3 test T-KID-RES-03 exercises it end-to-end against the
RFC-8032 Ed25519 test-vector seeds.

### 5.10 AIP-document transport-fetch operational contract (Phase-2 Sprint-4 Tag-4)

The transport-fetch layer plugs the §5.9 boundary item "AIP-document
transport-fetch": the kid-resolver (§5.9) presumes the caller has
already obtained the AIP document, but does not specify how. Sprint-4
Tag-4 ships that step as a pure composition of two existing Phase-1b
primitives — the V-908 HTTPS-transport (`HTTPSDocumentTransport`) and
the V-908 §3.4 DNS-anchor pattern — extended in shape from the FTD
document to the AIP document. The module is
`wirelang.identity.aip_document_transport_fetch`; it does NOT mutate
the schema-registry backend, does NOT add a method to
`NatsKvSchemaRegistry`, and does NOT introduce a new envelope.

**Module location and rationale:**

The fetcher lives in `wirelang.identity` alongside the kid-resolver
(§5.9), `aip_document.py`, `aip_signing.py`, and the V-908 transport
primitives (`aip_https_backend.py`, `dns_anchor.py`). This placement
keeps the AIP-document trust layer self-contained: the schema-
registry signing module (§5.8) sees only the resolved public key,
and the resolver (§5.9) sees only the parsed AIP-document body. The
transport step is upstream of both and is the natural concern of the
Identity-Substrate module.

**Public API:**

```python
@dataclass(frozen=True)
class AipFetchResult:
    aip_id: str                  # input identifier (aip:web: or https://)
    url: str                     # canonical HTTPS URL fetched
    host: str                    # lower-cased host (for the DNS-anchor lookup)
    aip_doc: dict                # parsed JSON body, ready for resolve_kid
    body_bytes: bytes            # raw HTTPS response bytes (for re-canonicalisation)
    jcs_sha256_hex: str          # SHA-256(JCS(body without document_signature))
    dns_anchor: Optional[DnsAnchor]
    anchor_matched: bool

def aip_web_to_https_url(aip_id: str) -> tuple[str, str]: ...

def fetch_aip_document(
    aip_id: str,
    *,
    transport: HTTPSDocumentTransport,
    dns_resolver: Optional[TxtResolver] = None,
    anchor_required: bool = False,
    dns_timeout_s: float = 3.0,
) -> AipFetchResult: ...

class AipDocumentTransportError(Exception): ...
class AipUrlSchemeError(AipDocumentTransportError): ...
class AipDnsAnchorMismatchError(AipDocumentTransportError): ...

WELL_KNOWN_AIP_PREFIX: str = "/.well-known/aip/"
DNS_ANCHOR_PREFIX: str = "_wakir-aip."
```

**URL mapping rules:**

| Input | Output URL | Output host |
|---|---|---|
| `aip:web:host/persona-path` | `https://host/.well-known/aip/persona-path.json` | `host` (lower-cased) |
| `aip:web:host` (no path) | `https://host/.well-known/aip/index.json` | `host` (lower-cased) |
| `aip:web:host/foo.json` | `https://host/.well-known/aip/foo.json` (trailing `.json` is stripped from path then added back so the canonical form is single-source) | `host` (lower-cased) |
| `https://host/...` (pre-resolved) | unchanged | `host` parsed from URL |
| `http://...` | (raises `AipUrlSchemeError`) | — |
| empty / malformed | (raises `AipUrlSchemeError`) | — |

The `aip:web:` shape is the Wakir Phase-2 convention paralleling the
W3C `did:web:` shape; the canonical resolution under the `.well-known`
namespace (RFC 8615) keeps AIP documents portable across any web host
without a custom registry.

**Transport delegation:**

HTTPS fetch is delegated wholesale to the Phase-1b V-908
`HTTPSDocumentTransport` (Tag-8 PS-6 module). The Tag-4 layer:

- Adds no transport invariants on top of the V-908 §3.3 set
  (HTTPS-only, TLS 1.2+, max redirect = 0, body size cap, JSON
  Content-Type, parseable JSON object root). The V-908 transport
  enforces them.
- Does NOT wrap V-908 transport-level exceptions. `HTTPSStatusError`
  (with `.status == 404` etc.), `HTTPSSchemeError`,
  `HTTPSTransportError`, `HTTPSBodySizeError`, `HTTPSPayloadError`,
  `HTTPSRedirectError`, `HTTPSDocumentNotModified`, and the base
  `HTTPSBackendError` propagate verbatim. Callers retain typed
  access to the V-908 §3.3 invariants and can implement
  cache-revalidation strategies (`If-None-Match`) without going
  through the Tag-4 surface.

The result is that Tag-4 is byte-thin over the existing transport:
no double-parsing, no transport-error-renaming, no JSON re-decode.

**DNS-anchor cross-check (Wakir-AIP variant of V-908 §3.4):**

The optional `dns_resolver` parameter enables an out-of-band TXT-record
lookup at `_wakir-aip.<host>` (prefix `DNS_ANCHOR_PREFIX`). The
TXT-record format is byte-identical to the V-908 §3.4 FTD-document
anchor:

```
v=1; sha256=<64-hex>
```

Parsing reuses `wirelang.identity.dns_anchor.parse_anchor` verbatim.
Only the prefix differs between the AIP variant (`_wakir-aip`) and the
FTD variant (`_wakir-ftd`) — same trust model, same on-wire shape.

The local fingerprint is computed as
`SHA-256(JCS(body without document_signature))` using the resolver-
indirected `_jcs_canonicalize` from `wirelang.identity.aip_signing`
(the same canonicaliser the AIP-document signing path uses; the
`document_signature` slot is removed from a deep-copy so the caller's
body is not mutated).

**Hard-vs-soft toggle (`anchor_required`):**

| `anchor_required` | DNS TXT outcome | Result |
|---|---|---|
| `False` (default) | matches local JCS-anchor | `dns_anchor` set, `anchor_matched=True` |
| `False` (default) | missing / malformed | `dns_anchor=None`, `anchor_matched=False`, no raise |
| `False` (default) | mismatches | `dns_anchor` set, `anchor_matched=False`, no raise |
| `False` (default) | no resolver supplied | `dns_anchor=None`, `anchor_matched=False`, no raise |
| `True` | matches local JCS-anchor | `dns_anchor` set, `anchor_matched=True` |
| `True` | missing / malformed | **`AipDnsAnchorMismatchError`** (with `expected` set, `observed=None`) |
| `True` | mismatches | **`AipDnsAnchorMismatchError`** (with `expected` + `observed` set) |
| `True` | no resolver supplied | **`AipDnsAnchorMismatchError`** ("dns_resolver is None") — eager raise contract |

The `anchor_required` toggle is **orthogonal to** the Sprint-4 Tag-1
`VerifyMode.STRICT` signature-policy toggle (Z-1-K-Sprint-4-4) — it
governs the transport-trust step, not the signature-verification step.
A production deployment composes both:

- `VerifyMode.STRICT` for signature presence + cryptographic validity
  on the schema-registry envelope.
- `anchor_required=True` for DNS-anchored AIP-document trust.

**Determinism contract (Phase-2 Sprint-4 Tag-4 invariants):**

1. **Pure composition**: `fetch_aip_document` does not cache; it does
   not mutate the transport or the resolver; the result dataclass is
   frozen. Production callers compose with the existing V-908
   `HTTPSAipResolverCache` or a separate caching tier if memoisation
   is required.
2. **Reproducible URL mapping**: `aip_web_to_https_url` is byte-
   deterministic on its input. Repeated calls with the same `aip_id`
   produce equal `(url, host)` tuples.
3. **Reproducible byte-anchor**: `result.jcs_sha256_hex` is byte-equal
   across repeated fetches of the same body (the JCS canonicaliser
   is deterministic; the SHA-256 digest is deterministic).
4. **Structural-vs-network split**: structural failures (URL scheme,
   anchor mismatch in hard mode) raise the typed `AipDocument*`
   errors; network-level failures propagate as V-908
   `HTTPSBackendError` subclasses unchanged. Callers can branch on
   exception type without parsing messages.

**Phase-2 Sprint-4 Tag-4 boundary:**

The transport-fetch layer deliberately does NOT:

- Validate the AIP document's `document_signature` slot. Establishing
  AIP-document signing-trust is the caller's responsibility — see
  `wirelang.identity.verify_aip_signature`. The fetch layer returns
  the parsed body unchanged and lets the caller drive signature-check.
- Validate the AIP document against the JSON Schema
  (`wirelang/schemas/aip-document.json`). Schema-validation lives in
  Phase-1a `aip_resolver`; Tag-4 is shape-agnostic.
- Mutate the schema-registry backend surface. `NatsKvSchemaRegistry`
  is unchanged; no new method, no new envelope.
- Cache the result. Tag-4 is a stateless pure composition. The V-908
  `HTTPSAipResolverCache` exists in the HTTPS backend for the
  federation pipeline; production callers compose with the cache or
  layer their own tier on top.
- Bind the resolved `aip_id` to a schema-registry capability
  envelope (`registered_by` gating remains a future Phase-2 slot).

**Cross-Review-Zone-1 (Identity-Substrate) — non-touched:**

- **Z-1-K-Sprint-4-1 (kid-Resolver-Shape)** non-touched; Sprint-4
  Tag-3 closed it. Tag-4 feeds the resolver, does not modify it.
- **Z-1-K-Sprint-4-2 (JCS-Resolver-Lock)** non-touched; this module
  consumes `aip_signing._jcs_canonicalize` byte-identical via a
  lazy import. No new JCS path introduced.
- **Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519)** non-touched;
  transport-fetch is curve-agnostic (it fetches a document, not a
  key).
- **Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner)** non-touched;
  `anchor_required` is a Tag-4-local hard-vs-soft toggle and is
  semantically independent of the schema-registry signing STRICT
  toggle.

**Composition pattern (canonical end-to-end Phase-2 verifier flow):**

```python
from wirelang.identity import (
    fetch_aip_document,
    resolve_kid,
)
from wirelang.identity.aip_https_backend import HTTPSDocumentTransport
from wirelang.identity.dns_anchor import StdlibDoHResolver
from wirelang.schemas.entry_signing import verify_entry_signature, VerifyMode

# 1. Fetch and (optionally) DNS-anchor-cross-check the AIP document.
transport = HTTPSDocumentTransport()
dns = StdlibDoHResolver()
fetched = fetch_aip_document(
    "aip:web:wakir.dev/personas/treasury-issuer",
    transport=transport,
    dns_resolver=dns,
    anchor_required=True,        # hard-trust path
)

# 2. Resolve the signing kid to an Ed25519 public key.
resolved = resolve_kid(
    fetched.aip_doc,
    signed.signature["kid"],
    as_of=now_utc(),
    require_purpose="aip-signing",
)

# 3. Verify the schema-registry-entry signature end-to-end.
ok = verify_entry_signature(
    signed, resolved.public_key, mode=VerifyMode.STRICT,
)
```

Sprint-4 Tag-4 test `T-AIP-FT-11` exercises steps 1-2 against the
RFC-8032 Ed25519 test-vector seeds; the resolver feed-through to
`verify_entry_signature` is covered by Sprint-4 Tag-3 test
`T-KID-RES-03`. The two tests together pin the end-to-end Phase-2
verifier pattern.

### 5.11 AIP-document signature-verification cache tier (Phase-2 Sprint-4 Tag-5)

The verification-cache tier is a stateful, bounded LRU+TTL cache on
top of the Sprint-4 Tag-1 AIP-document signing primitive
(`wirelang.identity.verify_aip_signature`). The Tag-1 verifier is
pure and stateless; the §5.11 cache memoises its Boolean outcome
to short-circuit re-verification cost on repeated calls with the
same `(body, signature, public_key)` triple. The module is
`wirelang.identity.aip_signature_verification_cache`; it does NOT
mutate the schema-registry backend, does NOT add a method to
`NatsKvSchemaRegistry`, and does NOT introduce a new envelope.

**Module location and rationale:**

The cache lives in `wirelang.identity` alongside the kid-resolver
(§5.9), the transport-fetch (§5.10), `aip_signing.py`, and the
V-908 transport primitives. The placement keeps the AIP-document
trust layer self-contained: the schema-registry signing module
(§5.8) is unchanged; the kid-resolver (§5.9) is unchanged; the
transport-fetch (§5.10) is unchanged. The cache sits at the same
Identity-Substrate layer as the underlying verifier and composes
with it byte-orthogonally (the verifier is the cache's single
miss-path target; no other module's surface is touched).

**Public API:**

```python
DEFAULT_MAX_ENTRIES: int = 256
DEFAULT_TTL_SECONDS: float = 300.0

@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    expired: int = 0
    size: int = 0   # live snapshot, not cumulative

class AipSignatureVerificationCache:
    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None: ...

    @property
    def stats(self) -> CacheStats: ...   # defensive copy
    @property
    def max_entries(self) -> int: ...
    @property
    def ttl_seconds(self) -> float: ...

    def verify(
        self, aip_doc: dict, signature_block: dict, pub_key: bytes,
    ) -> bool: ...

    def clear(self) -> None: ...
    def evict_expired(self) -> int: ...

def cached_verify_aip_signature(
    aip_doc: dict,
    signature_block: dict,
    pub_key: bytes,
    *,
    cache: AipSignatureVerificationCache,
) -> bool: ...
```

**Cache-key construction:**

The cache key is the SHA-256 of an explicit 5-tuple, byte-serialised
with `\x00` separators (no JSON, no canonicalisation cost — the
inputs are already canonicalised individually):

1. `SHA-256(JCS(body without document_signature))` hex of the
   AIP-document body. Identical in shape to the Sprint-4 Tag-4
   `jcs_sha256_hex` byte-anchor; reuses the same resolver-indirected
   `_jcs_canonicalize` from `aip_signing` (Z-1-K-Sprint-4-2 lock
   preserved).
2. `signature_block["alg"]` (`"Ed25519"` for the Phase-2 default
   curve; future-proof for additional curves).
3. `signature_block["kid"]` string.
4. `signature_block["signature"]` hex (128 chars for Ed25519).
5. `pub_key.hex()` (the 32-byte raw Ed25519 public key, in hex).

The 5-tuple captures every input of the underlying verify call.
Distinct inputs (different body, different alg, different kid,
different signature hex, different public-key bytes) produce
different cache keys; reflexive inputs collide. The
`document_signature` slot is stripped from the body before JCS-
canonicalisation; re-publishing the same body with a different
`document_signature` slot produces the same cache key (the cache
is bound to the body content, not to whatever attached signature
it travelled with at fetch time).

The SHA-256 indirection keeps the cache-key memory cost
bounded regardless of the AIP-document size; the document is hashed
upstream of the cache, and the cache only stores the digest.

**Cache semantics:**

- **Hits return the memoised Boolean unchanged.** A hit does not
  re-invoke `verify_aip_signature`. The contract is "cache hit is
  byte-equal to a fresh verify" — production callers can rely on
  hit/miss being a pure performance optimisation, not a behavioural
  difference.
- **TTL expiry on lookup**: when a hit is found but
  `now - entry.inserted_at >= ttl_seconds`, the entry is removed
  and the lookup falls through to a fresh verify. The `expired`
  counter increments; the `hits` counter does NOT. The clock is
  injectable via the `clock` constructor argument (defaults to
  `time.monotonic`); hermetic tests inject a controllable callable.
- **LRU eviction on insertion**: if the cache is at `max_entries`
  capacity, the oldest entry by insertion-order is removed. A
  cache *hit* does NOT promote the entry; LRU is by insertion-
  order, byte-identical to the V-908 `HTTPSAipResolverCache`
  semantics for cross-cache consistency.
- **Negative caching**: a `False` verify outcome is cached the
  same way as a `True` outcome. Production fleets that see retries
  against known-bad inputs (expired key rotations, replayed
  malicious signatures, etc.) benefit from the negative cache.
- **Structural failures are NOT cached**: when
  `verify_aip_signature` raises `ValueError` (malformed signature
  block, wrong algorithm, wrong key length), the exception
  propagates verbatim and no cache entry is written. The cache
  contract: "cache stores Boolean verify outcomes; structural
  failures bubble through unchanged".
- **clear() drops entries; counters survive**: `clear()` empties
  the cache contents but does NOT reset the lifetime counters
  (`hits` / `misses` / `evictions` / `expired` survive). The
  `size` field on `stats` is live and naturally drops to zero.
- **evict_expired() out-of-band sweep**: an explicit method walks
  the cache and removes every entry beyond the TTL window. Useful
  for production callers that want a periodic timer-driven sweep
  to keep the live size bounded by freshness rather than by LRU.

**TTL window rationale:**

The default TTL of 300 seconds balances two production scenarios:

1. **Key rotation**: an AIP document's `public_keys` entry has a
   `validuntil` window. A cached verify outcome past that window
   may no longer reflect current trust policy; the TTL forces a
   re-verify with the latest document-state at most every
   `ttl_seconds`.
2. **Document mutation**: an AIP document may be re-published with
   a new `document_signature` slot at the same identifier. The
   cache key includes the body's JCS-anchor so a re-publication
   with a different body is a different cache key naturally; the
   TTL is defence-in-depth for the unlikely case where the same
   JCS-anchor reappears under mutated semantics.

Callers with stricter freshness requirements can construct a
shorter-TTL cache or call `evict_expired()` on their own cadence.

**Determinism contract (Phase-2 Sprint-4 Tag-5 invariants):**

1. **Byte-equal hit vs miss outcomes**: for any `(aip_doc,
   signature_block, pub_key)` triple, `cache.verify(...)` returns
   the same Boolean whether the call is a hit or a miss. The cache
   is a pure performance optimisation.
2. **Deterministic cache-key construction**: `_build_cache_key`
   is byte-deterministic on its inputs. Repeated calls with byte-
   equal inputs produce equal keys; any byte-difference in the
   5-tuple produces a different key.
3. **Hermetic-clean TTL semantics**: the `clock` parameter accepts
   any callable returning a monotonic float. Tests inject a
   controllable clock; production injects `time.monotonic`. TTL
   transitions are deterministic on the injected clock.
4. **Negative-vs-structural-failure split**: cryptographically-
   wrong outcomes (`False`) are memoised; structural failures
   (`ValueError`) are NOT. Callers can rely on the cache to bound
   re-verification cost for stable inputs without masking
   structural bugs at the input layer.

**Phase-2 Sprint-4 Tag-5 boundary:**

The verification-cache tier deliberately does NOT:

- Replace `wirelang.identity.verify_aip_signature`. The cache is a
  thin composition on top; the underlying verifier remains the
  single source of truth for cryptographic correctness.
- Cache transport-fetch outputs. The Sprint-4 Tag-4
  `aip_document_transport_fetch` layer is upstream and stateless;
  the V-908 `HTTPSAipResolverCache` caches *documents* (by URI and
  ETag) at the federation pipeline. The Tag-5 cache memoises the
  *verify outcome*, a different cache key shape.
- Persist across process boundaries. The cache is in-process only;
  distributed-cache contracts (Redis / NATS-KV / shared filesystem)
  are Phase-3 slots.
- Mutate `wirelang.identity.sign_aip_document` or any signing-side
  surface. Tag-5 is read-side only.
- Bind the cached verify outcome to a schema-registry capability
  envelope (`registered_by` gating remains a future Phase-2 slot).

**Cross-Review-Zone-1 (Identity-Substrate) — non-touched:**

- **Z-1-K-Sprint-4-1 (kid-Resolver-Shape)** non-touched; the cache
  takes a `pub_key` argument the caller has already resolved (via
  the §5.9 kid-resolver). The cache does NOT import `kid_resolver`
  or invoke it.
- **Z-1-K-Sprint-4-2 (JCS-Resolver-Lock)** non-touched; this module
  consumes `aip_signing._jcs_canonicalize` byte-identical via a
  direct import. No new JCS path; the cache-key body digest is
  byte-equal to the Sprint-4 Tag-4 `_jcs_anchor_hex` shape.
- **Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519)** non-touched; the
  cache is curve-agnostic by construction. The `alg` field is part
  of the cache key but the cache does not enforce a curve choice —
  the underlying verifier enforces it.
- **Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner)** non-touched;
  the cache is policy-agnostic. It memoises the Boolean outcome of
  the verifier; the caller's STRICT-mode policy (Sprint-4 Tag-1
  `VerifyMode.STRICT`) is upstream and unchanged.

**Composition pattern (canonical end-to-end Phase-2 cached-verifier flow):**

```python
from wirelang.identity import (
    AipSignatureVerificationCache,
    fetch_aip_document,
    resolve_kid,
)
from wirelang.identity.aip_https_backend import HTTPSDocumentTransport
from wirelang.identity.dns_anchor import StdlibDoHResolver

# 1. Fetch and (optionally) DNS-anchor-cross-check the AIP document
#    (Sprint-4 Tag-4, §5.10).
transport = HTTPSDocumentTransport()
dns = StdlibDoHResolver()
fetched = fetch_aip_document(
    "aip:web:wakir.dev/personas/treasury-issuer",
    transport=transport,
    dns_resolver=dns,
    anchor_required=True,
)

# 2. Resolve the document_signature.kid to an Ed25519 public key
#    (Sprint-4 Tag-3, §5.9).
sig_block = fetched.aip_doc["document_signature"]
resolved = resolve_kid(
    fetched.aip_doc, sig_block["kid"], as_of=now_utc(),
)

# 3. Verify the AIP-document signature through the cache tier
#    (Sprint-4 Tag-5, this section). Repeated calls with byte-equal
#    inputs short-circuit through the memoised outcome.
cache = AipSignatureVerificationCache()  # singleton in production
ok = cache.verify(fetched.aip_doc, sig_block, resolved.public_key)
```

Sprint-4 Tag-5 test `T-AIP-SVC-02` pins the hit-on-second-verify
byte-equality with a fresh `verify_aip_signature` call; T-AIP-SVC-03
pins the TTL invalidation through an injectable clock; T-AIP-SVC-04
pins the LRU eviction by insertion-order; T-AIP-SVC-05 pins the
negative-caching round-trip; T-AIP-SVC-08 pins the structural-
failure non-caching contract.

### 5.12 `registered_by`-capability-gating operational contract (Phase-2 Sprint-4 Tag-6)

The capability-gating layer is the Layer-3 authorisation tier for
Phase-2 schema-registry signing. It binds the `registered_by`
field of a `SchemaRegistryEntry` to an in-memory policy bundle that
constrains *which* signing keys (`kid`) and *which* `(layer, name)`
schema triples a given publisher identity is authorised to register.
The gate is *additive* policy on top of the Sprint-4 Tag-1
`verify_entry_signature` cryptographic primitive: a cryptographically
valid signature can still be denied if the issuer lacks capability
over the registered triple. Cryptographic correctness remains the
single source of truth in `wirelang.schemas.entry_signing` and is
UNCHANGED.

**Module location and rationale:**

The capability-gating module lives in `wirelang.schemas` alongside
`entry_signing` (§5.8) and the existing registry-side surfaces
(`registry_nats_kv_backend`, `publisher_cli`, `replication`). The
placement keeps the schema-registry trust layer self-contained: the
entry-signing module (§5.8) is unchanged; the kid-resolver (§5.9) is
unchanged; the transport-fetch (§5.10) is unchanged; the
verification cache (§5.11) is unchanged. The gate sits at the
schema-registry-Layer-3 (capability-token-layer-prelude) and
composes with the entry-signing module byte-orthogonally
(`gate_signed_entry` takes a `SignedSchemaRegistryEntry` from §5.8
and routes its `entry` and `signature` into the policy check).

**Public API:**

```python
class RegisteredByCapabilityError(Exception): ...

class DecisionSource(enum.Enum):
    POLICY_MATCH = "policy_match"
    POLICY_DISABLED = "policy_disabled"
    NO_POLICY_FOR_ISSUER = "no_policy_for_issuer"
    KID_NOT_ALLOWED = "kid_not_allowed"
    TRIPLE_NOT_ALLOWED = "triple_not_allowed"
    OUTSIDE_VALIDITY_WINDOW = "outside_validity_window"

@dataclass(frozen=True)
class CapabilityPolicy:
    registered_by: str
    allowed_kids: tuple[str, ...]
    allowed_triples: tuple[tuple[str, str], ...]
    not_before: Optional[datetime] = None
    not_after: Optional[datetime] = None
    disabled: bool = False
    note: Optional[str] = None

    def covers_triple(self, layer: str, name: str) -> bool: ...

@dataclass(frozen=True)
class CapabilityGateDecision:
    allowed: bool
    reason: str
    source: DecisionSource
    policy: Optional[CapabilityPolicy] = None

class CapabilityPolicyRegistry:
    def add_policy(self, policy: CapabilityPolicy) -> None: ...
    def policies_for(self, registered_by: str) -> tuple[CapabilityPolicy, ...]: ...
    def list_issuers(self) -> tuple[str, ...]: ...

def check_registered_by_capability(
    entry: SchemaRegistryEntry,
    signature_block: Mapping[str, Any],
    registry: CapabilityPolicyRegistry,
    *,
    as_of: Optional[datetime] = None,
) -> CapabilityGateDecision: ...

def gate_signed_entry(
    signed: SignedSchemaRegistryEntry,
    registry: CapabilityPolicyRegistry,
    *,
    as_of: Optional[datetime] = None,
) -> CapabilityGateDecision: ...
```

**Policy bundle semantics:**

1. **`registered_by`** is matched byte-exactly to the entry's
   `registered_by` field. Two policies under the same identity are
   explicitly supported (per-kid or per-layer splits); the gate
   iterates the per-issuer list FIFO.
2. **`allowed_kids`** is a non-empty tuple of `kid` strings. The
   entry's `signature_block["kid"]` MUST be a member. Tag-6 ships
   exact-string set-membership; glob/regex on the kid axis is a
   Phase-3 slot.
3. **`allowed_triples`** is a non-empty tuple of
   `(layer, name_glob)` pairs. The entry's `(layer, name)` MUST
   match at least one pair. Layer matching is literal with `"*"` as
   the all-layers wildcard. Name matching follows :mod:`fnmatch`
   grammar (`*` / `?` / `[seq]`). Tag-6's name-glob choice is
   deliberately conservative: more expressive policy languages
   (regex, Datalog) are Phase-3 slots.
4. **`not_before` / `not_after`** define a validity window for the
   policy itself (not for the entry being gated). When `as_of` is
   supplied to the gate call, it MUST satisfy
   `not_before <= as_of < not_after`. `None` on either bound
   disables the corresponding check. Production verifier paths
   SHOULD supply `as_of`; omitting it bypasses the window check
   (consistent with the Sprint-4 Tag-3 `resolve_kid` `as_of`
   contract).
5. **`disabled=True`** is a kill-switch. A disabled policy never
   matches; if all candidate policies for an issuer are disabled,
   the gate returns a deny with source `POLICY_DISABLED`.
6. **`note`** is a free-form audit string carried verbatim into
   the decision's `policy` field (useful for downstream logs).

**Gate decision shape:**

`CapabilityGateDecision(allowed, reason, source, policy)`. Frozen;
equality-by-value. The `reason` is a free-form audit string
suitable for downstream logs; the `source` enum lets consumers
distinguish *why* a decision was reached without parsing the
string. The `policy` field is the matched policy for an allow / the
attempted-but-rejected policy for a deny-by-policy / `None` for
`NO_POLICY_FOR_ISSUER`.

**Deny precedence ordering:**

When iteration encounters multiple non-matching policies, the
gate records the *most specific* failure for the audit log:

```
POLICY_DISABLED < KID_NOT_ALLOWED < TRIPLE_NOT_ALLOWED < OUTSIDE_VALIDITY_WINDOW
```

A later policy's higher-precedence deny *replaces* an earlier
lower-precedence deny in the recorded fallback. This is structural
ordering only; the iteration itself is FIFO over the registry's
per-issuer policy list. Rationale: a deny by *missing window* is
more informative than a deny by *wrong triple*, which is more
informative than *wrong kid*, which is more informative than
*disabled*. Audit logs surface the most-specific failure.

**Determinism contract (Phase-2 Sprint-4 Tag-6 invariants):**

1. **Pure-function gating:** `check_registered_by_capability` is a
   pure function of `(entry, signature_block, registry-state,
   as_of)`. Identical inputs produce byte-identical decisions
   (frozen dataclass equality).
2. **Caller-supplied `kid`:** the gate consumes
   `signature_block["kid"]` byte-equal as the caller supplied it.
   It does NOT call the Sprint-4 Tag-3 `kid_resolver`; the kid →
   public-key resolution is upstream and unchanged.
3. **No mutation of inputs:** the policy bundle is frozen, the
   registry is mutated only via `add_policy`, and the gate call
   never mutates anything. A defensive tuple snapshot is returned
   from `policies_for`; subsequent `add_policy` calls do not
   retroactively appear in earlier snapshots.
4. **No transport, no I/O:** the gate is in-process only; no NATS
   call, no DNS lookup, no HTTPS fetch. Production callers wire
   policy distribution via a separate (Phase-3) channel.

**Phase-2 Sprint-4 Tag-6 boundary:**

- This module does NOT ship Biscuit binary token encode/decode +
  Datalog caveat evaluation. The on-the-wire Biscuit-v3 JSON
  envelope schema lives at
  `wirelang/schemas/layer-3-capability-token.json` since Phase-1a
  and is referenced as the *target* shape for Phase-3
  substantiation. Tag-6 is a *prelude*: a simpler in-process policy
  bundle that captures the Wakir-side intent without the full
  Biscuit machinery.
- ~~This module does NOT distribute or persist policies. The
  registry is in-process only; persisted distribution over a
  NATS-KV bucket (`wakir-capability-policies` or analogous) is a
  Phase-3 slot.~~ (**CONSUMED in Sprint-5 Tag-2** —
  `wirelang.schemas.capability_policy_nats_kv_backend` ships the
  persistent-distribution tier on the `wakir-capability-policies`
  bucket; see §5.14. The Sprint-4 Tag-6 in-process
  `CapabilityPolicyRegistry` remains the evaluation surface;
  Sprint-5 Tag-2 ships the source-of-truth substrate that
  materialises it via `NatsKvCapabilityPolicyBackend.snapshot_registry`.)
- This module does NOT plumb gating into the schema-registry write
  path. `NatsKvSchemaRegistry` is UNCHANGED. The gate is a
  callable layer; consumers (publisher CLI, future write-path
  middleware) wire it explicitly between `sign_entry` and `put`.
- This module does NOT replace
  `wirelang.schemas.entry_signing.verify_entry_signature`. The
  cryptographic primitive remains the single source of truth for
  signature correctness; the Tag-6 gate is *additional*
  authorisation policy.

**Cross-Review-Zone-1 (Identity-Substrate) non-touched:**

- Z-1-K-Sprint-4-1 (kid-Resolver-Shape) is consumed *upstream* by
  the caller; Tag-6 takes the `signature_block["kid"]` byte-equal
  as the caller supplied it and checks set-membership against
  `allowed_kids`. Tag-6 does NOT import or call
  `wirelang.identity.kid_resolver`.
- Z-1-K-Sprint-4-2 (JCS-Resolver-Lock) is non-touched: Tag-6 does
  not canonicalise anything; it is policy-evaluation only.
- Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519) is reinforced
  indirectly: Tag-6 operates on the entry-signing layer which is
  Ed25519, but Tag-6 carries no curve choice of its own.
- Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner) is non-touched:
  Tag-6 is *additional* policy and is orthogonal to the
  `VerifyMode` toggle (which gates the *cryptographic*
  signature requirement). A registry running `VerifyMode.STRICT`
  may also run Tag-6 capability-gating; the two checks compose
  independently.

**Composition pattern (canonical Phase-2 capability-gated publish flow):**

```python
# Production publish flow with capability gating:
from wirelang.identity import fetch_aip_document, resolve_kid
from wirelang.identity import AipSignatureVerificationCache
from wirelang.schemas.entry_signing import (
    sign_entry, verify_entry_signature, VerifyMode,
)
from wirelang.schemas.registered_by_capability import (
    CapabilityPolicyRegistry, gate_signed_entry,
)

# 1. Author signs the entry.
signed = sign_entry(entry, my_priv_key, kid="biscuit-root-1")

# 2. Cryptographic verification (Sprint-4 Tag-1 §5.8).
ok = verify_entry_signature(
    signed, my_pub_key, mode=VerifyMode.STRICT,
)
assert ok, "signature does not verify"

# 3. Capability gating (Sprint-4 Tag-6, this section).
decision = gate_signed_entry(signed, capability_registry)
if not decision.allowed:
    raise RuntimeError(
        f"capability deny ({decision.source.value}): "
        f"{decision.reason}"
    )

# 4. Routine publish (Sprint-3 Tag-1 / Tag-3 / Tag-5).
await backend.put_with_revision(
    signed.entry, expected_revision=0,
)
```

Sprint-4 Tag-6 test `T-RBC-02` pins the matching-policy allow with
the policy-reference roundtrip; T-RBC-04 pins the kid-not-allowed
deny and the multi-policy short-circuit; T-RBC-05 pins the layer
and name dimensions of triple-not-allowed separately; T-RBC-09 pins
the validity-window semantics (inclusive `not_before`, exclusive
`not_after`, `as_of`-omitted bypass); T-RBC-10 pins the
`gate_signed_entry` end-to-end composition with `sign_entry`;
T-RBC-12 pins the registry's defensive-snapshot semantics and the
deny-precedence ordering.

#### 5.12.1 Revocation operational contract (Phase-2 Sprint-6 Tag-1, additive over Sprint-4 Tag-6 and Sprint-5 Tag-2..5)

Phase-2 Sprint-6 Tag-1 adds an *explicit revocation* axis to
`CapabilityPolicy` that is distinct from the Sprint-4 Tag-6
`disabled` soft kill-switch. The split is deliberate:

- `disabled=True` is a **reversible operator-side state** ("this
  policy is paused for now; we may re-enable it later"). The
  Sprint-4 Tag-6 spec wording is intentionally non-committal.
- `revoked_at != None` is an **irreversible authority gesture**
  ("this policy MUST never be re-enabled; the operator declared a
  compromise"). Revocation is monotonic at the CAS-pin write path.

The on-the-wire envelope (`wakir.wirelang.capability-policy-entry/1`)
remains the single value schema; Tag-1 adds two optional fields:

| Field | Type | Default | Semantics |
|---|---|---|---|
| `revoked_at` | RFC-3339 datetime string \| null | null | wall-clock instant at which the policy becomes categorically revoked |
| `revocation_reason` | string \| null | null | free-form audit string; requires `revoked_at` to be set |

The decoder treats missing keys as `None` so Sprint-5 Tag-2..5
envelopes (without these keys) decode byte-equally to unrevoked
policies. The encoder always emits both keys (`null`-explicit when
absent) so on-the-wire payloads are deterministic.

**Gate-precedence amendment.** The Sprint-4 Tag-6 fallback ordering
(`POLICY_DISABLED` → `KID_NOT_ALLOWED` → `TRIPLE_NOT_ALLOWED` →
`OUTSIDE_VALIDITY_WINDOW`) is amended: `POLICY_REVOKED` outranks
all four. The gate inspects each candidate policy in order:

1. If `_is_revoked(policy, as_of)` is True, set the deny-fallback
   to `POLICY_REVOKED` (unless already set; the first revoked
   candidate fixes the decision policy reference).
2. Otherwise fall through to the Sprint-4 Tag-6 disabled / kid /
   triple / window cascade.
3. The first allow-match short-circuits to `POLICY_MATCH` as
   before; a revoked candidate **never** produces an allow.

The `_is_revoked` predicate is *categorical*: when `as_of=None` a
revoked policy is treated as revoked unconditionally. This is
deliberately stricter than `_window_contains`, which skips on
`as_of=None`. A revocation must never be silently bypassed by a
verifier that omits a clock.

**CAS-pin monotonicity contract.** The
`NatsKvCapabilityPolicyBackend.put_with_revision` path gains a
pre-CAS `Gate 3` check (Gates 1 and 2 are the Sprint-5 Tag-4
record-type and pair-key-derivation gates; Gate 3 is the new
revocation-monotonic gate). The gate reads the live record at the
key; if it carries `revoked_at != None`, the incoming record MUST
either preserve that instant byte-equally or refuse:

| Live state | Incoming state | Outcome |
|---|---|---|
| `revoked_at=None` | any | permitted (this is a fresh write or non-revoked update) |
| `revoked_at=T` | `revoked_at=T` (same instant) | permitted (idempotent rewrite; `revocation_reason` refresh is legal) |
| `revoked_at=T` | `revoked_at=None` | `CapabilityPolicyRevocationConflict` (un-revoke is forbidden) |
| `revoked_at=T` | `revoked_at=T'` (T' ≠ T) | `CapabilityPolicyRevocationConflict` (revocation instant cannot be moved, whether earlier or later) |

Gate 3 runs **before** the underlying KV update call, so a rejected
revocation attempt does not advance the live revision. The
exception carries the `key`, the `existing_revoked_at`, and the
`proposed_revoked_at` for downstream audit.

**LWW non-enforcement.** The Sprint-5 Tag-2 `put` (LWW) path does
NOT enforce revocation-monotonicity. This is consistent with the
Sprint-5 Tag-4 rationale: LWW writes are operator-deliberate and
the CAS-pin path is the safety-invariant guard. An operator who
deliberately wants to un-revoke must use the LWW path AND accept
the audit consequences (the revocation event remains in the bucket
history depth, retrievable for the configured `history=5` window).

**Watch-stream surface (Sprint-5 Tag-5 unchanged).** A revocation
write appears as one PUT event with `event.record.policy.revoked_at
!= None`. Consumer-side filters can subscribe to revocation events
specifically by filtering on this predicate; the watch-stream
substrate itself remains a strict suffix of the durable bucket
history without any revocation-specific handling.

**Cross-Review-Zone-1 (Identity-Substrate) non-touched.** Revocation
is a policy-layer authority gesture, not a cryptographic primitive.
The four Z-1-K-Sprint-4 consensus points (kid-resolver shape,
JCS-resolver lock, curve choice Ed25519, STRICT-mode activation
owner) remain byte-identical.

**Cross-Review-Zone-B (Kai NATS-KV) non-touched.** The
`wakir-capability-policies` bucket configuration is byte-unchanged
— `history=5` already retains the pre-revocation envelope for
audit. No new bucket; no `BucketSpec` mutation on the
orchestrator-side `PHASE_1_BUCKETS` inventory.

**Boundary: Sprint-6 Tag-1 does NOT ship (explicit).**

1. Publisher-CLI `--revoke` flag composing the CAS-pin revocation
   path — Sprint-6 Tag-1+ candidate; the API surface is reachable
   today via direct Python use of `put_with_revision`.
2. Watch-stream consumer-side revocation-event filter helper — the
   client-side filter is one-liner Python (`event.record.policy.
   revoked_at != None`); a dedicated helper is Sprint-6 Tag-1+
   candidate.
3. Cross-bucket revocation replication (extend Sprint-3 Tag-6
   replication to carry revoked policies byte-precisely) —
   Sprint-6 Tag-2+ candidate.
4. Full Biscuit v3 binary-token revocation-list interpretation —
   Phase-3 substrate; lives in the Datalog evaluation layer per
   `wirelang/schemas/layer-3-capability-token.json`. Sprint-6
   Tag-1 ships *policy-level* revocation, not *token-level*
   revocation. A revoked policy denies all future entries that
   would have been signed under it; an issued-and-presented
   token-burst is not invalidated retroactively (token-burst
   freshness is a separate Phase-3 axis).
5. `NatsKvSchemaRegistry` mutation — schema-registry backend
   byte-unchanged. Revocation lives entirely on the capability-
   policy backend.
6. Authority delegation (e.g. an operator-side multi-signature
   guard on revocation writes) — bucket-level access control is
   operator-side; the Wirelang layer ships the monotonicity
   invariant and leaves the authority gesture to operator policy.

### 5.13 Publisher-CLI capability integration (Phase-2 Sprint-5 Tag-1)

Phase-2 Sprint-5 Tag-1 lifts the Sprint-4 Tag-6 capability gate into
the publisher-CLI operator surface. The integration is **additive
over Sprint-4 Tag-6**: the Sprint-4 Tag-1 `sign_entry` primitive and
the Sprint-4 Tag-6 `gate_signed_entry` composition helper are wired
in between `_build_entry` and the backend `put` / `put_with_revision`
call. No new validation gate runs on the backend side; the on-the-wire
envelope is byte-unchanged; a deny short-circuits before the backend
connect so the `wakir-schemas` bucket is never touched on a deny.

#### Public CLI surface additions

```text
publish | dry-run
    [...pre-Sprint-5 flags unchanged...]
    [--sign]
    [--kid KID]
    [--ed25519-priv-key-hex HEX | --ed25519-priv-key-file PATH]
    [--gate]
    [--capability-registry PATH]
    [--gate-as-of RFC3339]
```

Three concerns are wired in:

1. **Signing** — `--sign` plus exactly one of `--ed25519-priv-key-hex`
   / `--ed25519-priv-key-file` and a `--kid` value. The CLI calls
   `wirelang.schemas.entry_signing.sign_entry(entry, priv_key,
   kid=kid)` and reflects `signed=True` / `kid=<value>` in the
   receipt. Argparse's mutually-exclusive group enforces the
   hex-vs-file disjunction at parse time; the consistency helper
   (`_validate_capability_flag_consistency`) enforces that at least
   one key source is present and that `--kid` is non-empty.

2. **Gating** — `--gate` plus `--capability-registry <path>`. The CLI
   loads the capability-registry JSON file via
   `_load_capability_registry`, runs
   `wirelang.schemas.registered_by_capability.gate_signed_entry(
   signed, registry, as_of=<parsed --gate-as-of>)`, and either
   short-circuits with `ExitCode.CAPABILITY_DENY` (7) on a deny or
   records the decision dict in the receipt's `gate_decision` field
   on an allow. The `--gate-as-of` flag is an optional RFC-3339
   instant used as the gate's `as_of` value; absent, the gate
   bypasses validity-window enforcement (byte-consistent with
   Sprint-4 Tag-6 §5.12 contract).

3. **Cross-flag invariants** — the consistency helper rejects all
   inconsistent flag combinations as `INPUT_ERROR` (exit 3) before
   any file is read or any backend connection is opened:

   - `--sign` requires `--kid` (non-empty).
   - `--sign` requires one of `--ed25519-priv-key-hex` /
     `--ed25519-priv-key-file`.
   - `--gate` requires `--sign` (the gate reads `kid` from the
     signature block).
   - `--gate` requires `--capability-registry`.
   - Orphan capability flags without `--sign` / `--gate` are usage
     errors (not silently ignored).

#### Capability-registry JSON file format

```json
{
  "policies": [
    {
      "registered_by": "wirelang-eng",
      "allowed_kids": ["biscuit-root-1"],
      "allowed_triples": [["wire", "layer-1-*"], ["*", "*"]],
      "not_before": "2026-05-01T00:00:00Z",
      "not_after":  "2027-05-01T00:00:00Z",
      "disabled": false,
      "note": "wirelang engineering publisher"
    }
  ]
}
```

The top-level object MUST contain a `policies` array; each entry is
mapped to a :class:`CapabilityPolicy` via `_policy_from_dict`.
Optional `not_before` / `not_after` are RFC-3339 strings with a
timezone (the loader normalises `Z` to `+00:00` and converts to UTC).
The `allowed_triples` field is a JSON array of two-element arrays
`[layer, name_glob]`; the loader converts each pair to a
`(str, str)` tuple before construction so the `CapabilityPolicy`
post-init validation runs on the canonical shape. Errors during
loading raise :class:`TypeError` / :class:`ValueError` (file shape;
surfaced as `INPUT_ERROR`) or
:class:`RegisteredByCapabilityError` (policy shape; surfaced as
`VALIDATION_ERROR`).

#### Exit-code matrix extension

The Sprint-5 Tag-1 matrix adds **one** code; pre-Sprint-5 codes are
byte-unchanged:

| Code | Symbol             | Meaning                                                        |
|------|--------------------|----------------------------------------------------------------|
| 0    | `OK`               | publish or dry-run succeeded                                   |
| 2    | `USAGE_ERROR`      | argparse parse failure (missing required, mutex group)         |
| 3    | `INPUT_ERROR`      | file not found / not UTF-8 / not JSON / flag-consistency error |
| 4    | `VALIDATION_ERROR` | schema-body / signature / capability-policy structural failure |
| 5    | `CAS_CONFLICT`     | CAS-pin or create-only conflict                                |
| 6    | `BACKEND_ERROR`    | other backend / transport failure                              |
| 7    | `CAPABILITY_DENY`  | **NEW** — `--gate` evaluated to a deny                         |

#### Receipt-shape extension (additive)

The Sprint-5 Tag-1 receipt adds three optional fields; pre-Sprint-5
fields are byte-unchanged. Pre-Sprint-5 callers that omit the
capability flags receive a receipt whose new fields are at their
default-off values (`signed=false`, `kid=null`, `gate_decision=null`),
so consumers indexing by the legacy field set continue to read
byte-equal pre-existing fields and consumers indexing by the new
fields receive an unambiguous "feature-off" marker:

```json
{
  "mode": "lww",                       // unchanged
  "key": "schemas/wire/layer-1-wire/0.1.0",
  "layer": "wire",
  "name": "layer-1-wire",
  "version": "0.1.0",
  "schema_id": "https://wakir.dev/wirelang/schema/layer-1-wire/0.1.0",
  "schema_body_sha256": "<64 hex chars>",
  "revision": 1,
  "expected_revision": null,
  "registered_by": "wirelang-eng",
  "registered_at": "2026-05-11T13:00:00+00:00",
  "supersedes": null,
  "signed": true,                      // NEW: bool
  "kid": "biscuit-root-1",             // NEW: Optional[str]
  "gate_decision": {                   // NEW: Optional[dict]
    "allowed": true,
    "source": "policy_match",
    "reason": "<freeform reason>"
  }
}
```

The `gate_decision` object's `source` field carries the snake_case
:class:`DecisionSource` value (`policy_match` / `policy_disabled` /
`no_policy_for_issuer` / `kid_not_allowed` / `triple_not_allowed` /
`outside_validity_window`); consumers building audit pipelines can
filter on this without parsing the free-form `reason` string.

#### Pipeline ordering (canonical Sprint-5 capability-gated publish)

The Sprint-5 Tag-1 flow is the operator-CLI projection of the
Sprint-4 Tag-6 §5.12 Composition Pattern, with three differences
relative to the in-process code-block:

1. The verifier (`verify_entry_signature`) is NOT invoked on the
   publisher path — the operator signs with their own private key,
   so the signature is trusted by construction. Verification is the
   consumer-side concern (Sprint-4 Tag-1 §5.8 + Tag-5 §5.11 caching
   tier).

2. The capability registry is loaded from disk every CLI invocation
   (no caching across runs). This is a deliberate Sprint-5 Tag-1
   boundary: cross-invocation registry distribution / caching /
   subscription is the Phase-3 `wakir-capability-policies` NATS-KV
   bucket reservation (§7).

3. The signature block is **not** written to the bucket. Sprint-5
   Tag-1 publishes the underlying `SchemaRegistryEntry` only; the
   signature is local authorisation glue. Pushing the signed
   envelope onto the bucket is the Sprint-5 Tag-2+ slot (CLI flag
   `--sign --emit-envelope` plus a backend `put_envelope` method;
   neither shipped in Sprint-5 Tag-1).

#### Phase-2 Sprint-5 Tag-1 boundary (what this slot does NOT do)

- Does NOT push the signature block onto the `wakir-schemas` bucket.
  The signature stays operator-local; consumer-side verification is
  the Sprint-4 Tag-1 / Tag-3 / Tag-4 / Tag-5 stack and lives outside
  the publisher CLI.

- ~~Does NOT distribute capability policies. The registry is loaded
  from a local JSON file every invocation. NATS-KV-distribution of
  policies (bucket `wakir-capability-policies`) remains the Phase-3
  reservation per §5.12 / §7.~~ (**CONSUMED in Sprint-5 Tag-2** —
  `wirelang.schemas.capability_policy_nats_kv_backend` ships the
  `wakir-capability-policies` bucket and the
  `NatsKvCapabilityPolicyBackend` surface; see §5.14. Sprint-5 Tag-1
  publisher CLI is byte-unchanged: the `--capability-registry` flag
  still reads operator-local JSON. ~~A future `--capability-bucket`
  publisher-CLI flag that reads from the Sprint-5 Tag-2 bucket is a
  Sprint-5 Tag-3+ candidate; Sprint-5 Tag-2 is the substrate, not
  the CLI integration.~~ — **CONSUMED in Sprint-5 Tag-3**: the
  `--capability-bucket` flag and the
  `_load_capability_registry_from_bucket` helper close the
  operator-experience gap end-to-end, mutually exclusive with
  `--capability-registry`; the bucket-side gate decision is byte-equal
  to the file-side path, with the receipt's `gate_policy_source`
  field as the only audit difference. See §5.13's "Bucket policy
  source (Sprint-5 Tag-3)" subsection.)

- Does NOT introduce on-the-wire Biscuit binary tokens. The
  `--capability-registry` JSON file is operator-side only; the
  Phase-3 Biscuit v3 envelope shape (`layer-3-capability-token.json`)
  is unaffected.

- Does NOT modify `NatsKvSchemaRegistry`. No new method, no envelope
  shape change, no validation gate at write time. The backend
  surface is byte-identical to Sprint-3 Tag-1 / Tag-3 / Tag-5.

- Does NOT modify `entry_signing.sign_entry` or
  `gate_signed_entry`. Sprint-4 Tag-1 + Tag-6 primitives are
  imported and called byte-equal.

- Does NOT alter pre-Sprint-5 receipts beyond adding three optional
  fields at default-off values. The bare-publish path (no capability
  flags) emits a receipt with the same pre-Sprint-5 field set plus
  three trailing `false` / `null` / `null` values.

#### Cross-Review-Zone-1 non-touched (all four Z-1-K-Sprint-4 points)

- **Z-1-K-Sprint-4-1 (kid-Resolver-Shape):** Sprint-5 Tag-1 does NOT
  import `kid_resolver`; the operator supplies `--kid` directly.
- **Z-1-K-Sprint-4-2 (JCS-Resolver-Lock):** Sprint-5 Tag-1
  canonicalises nothing; signing-side canonicalisation lives inside
  `sign_entry` unchanged.
- **Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519):** Sprint-5 Tag-1
  carries the operator's Ed25519 seed via flag, byte-consistent
  with the entry-signing primitive.
- **Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner):** Sprint-5
  Tag-1 is orthogonal to `VerifyMode`; the publisher path does not
  invoke `verify_entry_signature` at all.

#### Composition pattern (canonical operator invocation)

```sh
# 1. Operator stages a policy file (one-time setup):
cat > capability-registry.json <<'EOF'
{
  "policies": [
    {
      "registered_by": "wirelang-eng",
      "allowed_kids": ["biscuit-root-1"],
      "allowed_triples": [["wire", "layer-1-*"]],
      "disabled": false
    }
  ]
}
EOF

# 2. Operator publishes a schema body with sign + gate:
python -m wirelang.schemas.publisher_cli publish \
    --schema-body layer-1-wire/0.1.0.json \
    --layer wire --name layer-1-wire --version 0.1.0 \
    --registered-by wirelang-eng \
    --sign \
    --kid biscuit-root-1 \
    --ed25519-priv-key-file ~/.config/wakir/biscuit-root-1.seed \
    --gate \
    --capability-registry capability-registry.json
```

Sprint-5 Tag-1 test `T-SR-PUB-CG-01` pins the loader round-trip;
`T-SR-PUB-CG-02` pins the `--sign` happy path receipt shape and
signature-verify round-trip; `T-SR-PUB-CG-03` pins the
`--sign --gate` happy path (POLICY_MATCH on a single-policy
registry); `T-SR-PUB-CG-04..06` pin the three deny axes
(`no_policy_for_issuer`, `kid_not_allowed`, `triple_not_allowed`)
each as exit-code 7 with the bucket left untouched;
`T-SR-PUB-CG-07..08` pin the cross-flag consistency rejections
(orphan flags, `--gate` without `--sign`, `--sign` without `--kid`
or key source); `T-SR-PUB-CG-09` pins the dry-run sign+gate path
including the deny-on-dry-run case; `T-SR-PUB-CG-10` pins the
receipt-shape forward-compat (default-off values for callers that
omit the capability flags).

#### Bucket policy source (Sprint-5 Tag-3, additive over Sprint-5 Tag-1)

Sprint-5 Tag-3 closes the operator-experience gap left by §5.14: the
publisher CLI gains the `--capability-bucket` flag (mutually
exclusive with `--capability-registry`) so a sign+gate publish can
draw its policies from the Sprint-5 Tag-2 persistent bucket
(`wakir-capability-policies`) instead of an operator-local JSON file.

**Public surface additions:**

- New flag `--capability-bucket` (argparse `store_true`, mutually
  exclusive with `--capability-registry` via an argparse
  `add_mutually_exclusive_group`).
- New flag `--capability-bucket-connect-url` (default
  `nats://127.0.0.1:4222`; routed to the capability-bucket factory
  on dispatch). The default is non-None so the flag does not need
  an "orphan" check when bucket mode is off — the connect URL is
  simply ignored.
- New receipt field `gate_policy_source: Optional[str]` with three
  possible values: `"file"` when `--capability-registry` was used,
  `"bucket"` when `--capability-bucket` was used, and `None` when
  `--gate` was not requested. The audit field is the only receipt
  difference between the two sources — gate decisions are byte-equal.
- New optional `capability_bucket_factory` kwarg on
  `publisher_cli.run()` (analogous to `connect_factory`). The
  default factory is
  `publisher_cli._default_capability_bucket_factory`, which connects
  to NATS-JetStream and opens
  `js.key_value("wakir-capability-policies")`. Tests inject a factory
  returning an in-memory mock backend.
- New helper `_load_capability_registry_from_bucket(factory,
  connect_url) -> CapabilityPolicyRegistry`: opens the bucket via
  the factory, calls
  `NatsKvCapabilityPolicyBackend.snapshot_registry()`, and closes
  the connection (cleanup is awaited in a `finally` block so the
  bucket connection is released even on a snapshot raise).
- The synchronous `_run_dry_run` is now a wrapper over the new
  async `_run_dry_run_async` (via `asyncio.run`); the bucket factory
  is reachable from the dry-run path on the same surface as
  `_run_publish`.

**Pipeline ordering:**

```text
1. argparse parse + mutex enforcement (--capability-registry XOR
   --capability-bucket).
2. _validate_capability_flag_consistency  (--gate requires one of the
   two sources; orphan flags rejected).
3. _load_schema_body + _build_entry.
4. sign_entry (if --sign).
5. Policy-source dispatch:
   - if --capability-bucket: open bucket factory →
     snapshot_registry() → close cleanup. registry materialised.
   - else if --capability-registry: _load_capability_registry(path).
   registry materialised.
6. gate_signed_entry(signed_entry, registry, as_of=as_of).
7. if not allowed: print CAPABILITY_DENY envelope, return 7
   (schema bucket NEVER touched).
8. if allowed (publish path): connect to schema bucket, put / put_with_revision.
   if allowed (dry-run path): print receipt directly.
9. Receipt carries gate_policy_source ∈ {"file", "bucket"}.
```

The bucket connection is opened once per CLI invocation and released
before any further work proceeds, mirroring the schema-bucket
connect / cleanup contract from Sprint-3 Tag-5. A poisoned bucket
envelope (non-JSON value, schema-URI mismatch, malformed
`allowed_triples`, etc.) raises `CapabilityPolicyBackendError` which
the CLI routes to `ExitCode.VALIDATION_ERROR = 4`; the schema bucket
remains untouched in that case.

**Flag-consistency table** (`_validate_capability_flag_consistency`
extended in Sprint-5 Tag-3):

| `--sign` | `--gate` | `--capability-registry` | `--capability-bucket` | Outcome |
|----------|----------|-------------------------|------------------------|---------|
| Y        | Y        | path                    | -                      | Y file source |
| Y        | Y        | -                       | Y                      | Y bucket source |
| Y        | Y        | path                    | Y                      | argparse mutex → exit 2 |
| Y        | Y        | -                       | -                      | INPUT_ERROR (exit 3): `--gate` needs a source |
| Y        | -        | path                    | -                      | INPUT_ERROR (exit 3): orphan `--capability-registry` |
| Y        | -        | -                       | Y                      | INPUT_ERROR (exit 3): orphan `--capability-bucket` |
| -        | -        | path or Y               | -                      | INPUT_ERROR (exit 3): orphan flags require `--gate` |

**Cross-source byte-equality** (T-SR-PUB-CB-10): for an operator
that stages byte-identical policies under both sources (e.g. a
JSON-file containing the same `(registered_by, allowed_kids,
allowed_triples)` triples as a bucket-side
`CapabilityPolicyRegistry.snapshot`), the resulting CLI receipt is
byte-equal *except* for `gate_policy_source`. The bucket is the
authoritative source on multi-host deployments; the JSON-file source
remains the operator-local single-host convenience.

**Boundary (Sprint-5 Tag-3 boundary, NOT shipped):**

- ~~No CAS-pin tier on the capability-policy bucket
  (`NatsKvCapabilityPolicyBackend.put` is LWW; Phase-3 slot).~~
  (**CAS-pin CONSUMED in Sprint-5 Tag-4** via
  `NatsKvCapabilityPolicyBackend.put_with_revision` /
  `.get_with_revision` and `CapabilityPolicyConflictError`; see
  §5.14's "CAS-pin operational contract (Sprint-5 Tag-4)"
  subsection. The Sprint-5 Tag-3 `--capability-bucket` flag is
  read-only — `snapshot_registry()` — so the CAS-pin write path is
  reachable today only via direct backend use; an operator-CLI
  composition of the write path is a Sprint-5 Tag-5+ candidate.)
- ~~No watch-stream on the capability-policy bucket (full-snapshot
  only; Phase-3 slot).~~ (**CONSUMED in Sprint-5 Tag-5** — the
  watch-stream consumer surface ships as
  `NatsKvCapabilityPolicyBackend.watch()` plus
  `LiveCapabilityPolicySnapshot`; the full-snapshot path remains
  supported and orthogonal. See §5.14 Watch-stream operational
  contract.)
- No `--capability-bucket` Biscuit-v3-binary-token interpretation
  (the bucket envelope is the Sprint-5 Tag-2 JSON shape; promotion
  to a Biscuit-binary-token shape is Phase-3).
- No mutation of `NatsKvSchemaRegistry` (the schema-registry
  backend's `put` / `put_with_revision` are byte-unchanged).
- No mutation of `NatsKvCapabilityPolicyBackend` (Sprint-5 Tag-2 is
  consumed byte-unchanged; the Tag-3 layer reads from the existing
  `snapshot_registry()` surface).
- No new bucket on the orchestrator inventory (Z-B non-touched;
  `wakir-capability-policies` is the Sprint-5 Tag-2 bucket consumed
  as-is).

**Composition pattern (canonical operator invocation, bucket source):**

```sh
# 1. Author publishes a policy to the bucket (one-time per
#    issuer / per policy-id; uses NatsKvCapabilityPolicyBackend.put,
#    e.g. via an operator script that materialises a
#    CapabilityPolicyRecord and writes it to wakir-capability-policies).

# 2. Operator publishes a schema body with sign + bucket-source gate:
python -m wirelang.schemas.publisher_cli publish \
    --schema-body layer-1-wire/0.1.0.json \
    --layer wire --name layer-1-wire --version 0.1.0 \
    --registered-by wirelang-eng \
    --sign \
    --kid biscuit-root-1 \
    --ed25519-priv-key-file ~/.config/wakir/biscuit-root-1.seed \
    --gate \
    --capability-bucket
```

The Sprint-5 Tag-3 test inventory `T-SR-PUB-CB-01..10` (see §6.10
addendum) pins the bucket-source happy path, the three deny axes
through the bucket source, the mutex enforcement, the orphan-flag
rejection, the poisoned-envelope route, the dry-run bucket path, and
the cross-source byte-equality contract. The auxiliary
`TestAuxBucketLoader` pins the factory-cleanup invariant and the
multi-policy sorted-key iteration order.

### 5.14 Capability-policy persistent distribution (Phase-2 Sprint-5 Tag-2)

Sprint-5 Tag-2 ships
`wirelang.schemas.capability_policy_nats_kv_backend`, the
persistent-distribution tier for the Sprint-4 Tag-6 in-process
`CapabilityPolicyRegistry`. The module persists capability policies
on a dedicated NATS-JetStream-KV bucket
(`wakir-capability-policies`) so policy authorship survives
operator-process restarts and so multi-host deployments can
distribute policies through the same cluster substrate that already
carries the schema registry (`wakir-schemas`), AIP cache
(`wakir-aip-cache`), FTD cache (`wakir-ftd-cache`), FTD poison-marker
(`wakir-ftd-poisoned`), schema-registry-storage reservation
(`wakir-schema-registry-entries`), and federation routes
(`wakir-federation-routes`).

#### Public surface

The module exports (Phase-2 Sprint-5 Tag-2 surface):

- `BUCKET_NAME = "wakir-capability-policies"` — the new 7th bucket
  on Kai's `PHASE_1_BUCKETS` inventory (Z-B paired-update pending).
- `BUCKET_CONFIG` — the mirror constant for the orchestrator-side
  `BucketSpec`: `history=5`, `ttl_seconds=0`,
  `max_value_size=16_384`, `storage="file"`, `replicas=1`,
  `description="Wirelang capability-policy persistent registry
  (Phase-2)"`. Drift-policy is identical to the Sprint-3 Tag-1
  schema-registry-backend: any cluster-side deviation surfaces as
  drift and is never auto-corrected.
- `VALUE_SCHEMA = "wakir.wirelang.capability-policy-entry/1"` — the
  schema-URI fragment embedded in every value envelope.
- `CapabilityPolicyRecord` — a frozen dataclass wrapping a Sprint-4
  Tag-6 `CapabilityPolicy` plus operator-side bookkeeping
  (`policy_id`, `registered_at`, `registered_by_publisher`).
- `NatsKvCapabilityPolicyBackend` — the async backend: `get`,
  `get_by_pair`, `put`, `delete`, `list_keys`, `snapshot`,
  `snapshot_registry`.
- `key_for_policy_pair(registered_by, policy_id)` and
  `pair_for_key(key)` — the bijective identity-pair-to-KV-key
  derivation (kebab-case ASCII components; no slashes; permitted
  regex on each axis).
- `CapabilityPolicyBackendError` / `CapabilityPolicyEnvelopeError`
  / `CapabilityPolicyValidationError` — the structural failure
  classes (mirroring the schema-registry-backend `SchemaRegistry*`
  hierarchy).

#### Bucket identity

The bucket is keyed by `(registered_by, policy_id)` collapsed into
`capability-policies/<registered_by>/<policy_id>`. The
`registered_by` axis matches the Sprint-4 Tag-6 `CapabilityPolicy`
field byte-equal (i.e. the same value that the schema-registry-entry
carries in its own `registered_by` field). The `policy_id` axis is
operator-supplied free-form (kebab-case ASCII, non-empty, no
slashes) and lets one issuer carry multiple independent policies
(per-kid-rotation, per-layer-split, ...). The schema-registry-side
analogue is the `(layer, name, version)` triple
(`schemas/<layer>/<name>/<version>`); the persistent-policy side
uses a 2-tuple because policies are issuer-bound, not
triple-bound — the triple-set lives inside the policy's
`allowed_triples` field.

#### Value envelope

The on-the-wire envelope is JSON with sorted keys and compact
separators. Required fields:

| Field                       | Type            | Notes                                      |
|-----------------------------|-----------------|--------------------------------------------|
| `schema`                    | string          | `"wakir.wirelang.capability-policy-entry/1"` exact |
| `registered_by`             | string          | non-empty; matches policy bundle           |
| `policy_id`                 | string          | non-empty, kebab-case ASCII                |
| `allowed_kids`              | array<string>   | non-empty                                  |
| `allowed_triples`           | array<[str,str]>| non-empty; each element a 2-tuple          |
| `not_before`                | string or null  | RFC-3339 UTC                               |
| `not_after`                 | string or null  | RFC-3339 UTC                               |
| `disabled`                  | boolean         | strict boolean (not a string)              |
| `note`                      | string or null  | free-form audit string                     |
| `registered_at`             | string          | RFC-3339 UTC                               |
| `registered_by_publisher`   | string          | non-empty; operator audit                  |

Note: `allowed_triples` is a JSON array of 2-element JSON arrays
(`[[layer, name_glob], ...]`), NOT an object map. This mirrors the
Python tuple structure of `CapabilityPolicy.allowed_triples` exactly
and is byte-stable across encoder runs.

#### Validation gates at write

`NatsKvCapabilityPolicyBackend.put` enforces at write time:

1. The record's embedded `CapabilityPolicy` bundle has already
   passed `CapabilityPolicy.__post_init__` (Sprint-4 Tag-6
   invariants: non-empty `registered_by`, non-empty `allowed_kids`,
   non-empty `allowed_triples`, valid validity window, ...). The
   record's `__post_init__` re-asserts the embedded-policy class
   and the operator-side bookkeeping (kebab-case `policy_id`,
   tz-aware `registered_at`, non-empty
   `registered_by_publisher`).
2. The KV key derived from
   `(record.policy.registered_by, record.policy_id)` matches the
   explicit key (defence in depth against mis-keying).

A malformed record raises `CapabilityPolicyValidationError` /
`RegisteredByCapabilityError` before any bucket I/O.

#### Decoder / poisoned-envelope contract

The envelope decoder round-trips through the Sprint-4 Tag-6
`CapabilityPolicy` constructor so every Sprint-4 Tag-6 invariant is
re-enforced at decode time. Malformed envelopes surface as
`CapabilityPolicyEnvelopeError` (the persistent layer wraps the
Sprint-4 Tag-6 `RegisteredByCapabilityError` so consumers can catch
on the persistence boundary). A poisoned (non-JSON, wrong schema,
missing field, malformed `allowed_triples` shape, non-boolean
`disabled`, ...) value raises
`CapabilityPolicyEnvelopeError` from `get` and aborts `snapshot` /
`snapshot_registry`; no half-broken registry is surfaced.

#### Snapshot semantics

`snapshot` returns a sorted-by-key list of `CapabilityPolicyRecord`
instances. Determinism contract: two back-to-back snapshots over the
same bucket state yield byte-equal records and byte-equal
sorted-key lists (Sprint-3 Tag-1 determinism analogue).

`snapshot_registry` is the convenience surface for verifier
materialisation: it iterates the snapshot and feeds each
`record.policy` into a fresh `CapabilityPolicyRegistry` via
`add_policy`. The Sprint-4 Tag-6 gate
(`check_registered_by_capability`) consumes the resulting registry
byte-identical to the in-process path — the only difference is the
registry's origin (NATS-KV-backed vs. operator-supplied at
construction).

Disabled policies are included in the materialised registry; the
gate evaluates them (Sprint-4 Tag-6 semantics: a disabled policy
contributes a fallback `POLICY_DISABLED` decision-source when no
allowing match was found). Operators evict a policy from the gate
entirely by calling `delete` and re-snapshotting.

#### Phase-2 Sprint-5 Tag-2 boundary

- This module ships the persistent-distribution tier. It does NOT
  replace the Sprint-4 Tag-6 in-process registry: operators who
  prefer the Sprint-5 Tag-1 `--capability-registry` JSON-file path
  continue to use that path. Both coexist:
  - JSON-file path: "policies you ship with your CLI invocation".
  - NATS-KV path: "policies you publish once for the cluster to
    discover".
- This module does NOT bake operator-side biometric / hardware key
  attestation into the policy envelope. Policy entries are
  trust-on-write: any publisher with write access to the bucket can
  register a policy. Bucket-level access control (NATS server
  authentication, account isolation) is the operator's
  responsibility.
- ~~This module does NOT auto-distribute policies to publisher-side
  in-process registries. Publishers materialise a registry from
  `snapshot_registry` on startup (or on a periodic refresh
  schedule); the live tail is reserved as a Phase-3 slot
  (analogous to the schema-registry watch-stream, Sprint-3 Tag-4).
  The Phase-2 Sprint-5 Tag-2 slot is full-snapshot only.~~ (**CONSUMED
  in Sprint-5 Tag-5** — the live tail
  `NatsKvCapabilityPolicyBackend.watch()` plus the
  `LiveCapabilityPolicySnapshot` consumer surface land here as the
  pattern-mirror on the schema-registry watch-stream from Sprint-3
  Tag-4. The full `snapshot_registry` path remains supported and
  orthogonal: operators can choose between (a) periodic full-snapshot
  refresh — cheap to reason about, expensive when policy turnover is
  high — and (b) bootstrap-once-plus-watch-stream — a single
  bootstrap snapshot followed by incremental `apply(event)` calls,
  amortising long-running supervisor cost. The watch-stream is a
  *consumer* surface; the synchronous gate
  `check_registered_by_capability` is unchanged. See the **Watch-stream
  operational contract (Sprint-5 Tag-5, additive over Sprint-5 Tag-4)**
  subsection below for the full specification.)
- ~~This module does NOT ship a CAS-pinned upsert path. Policies are
  LWW under the assumption that policy authorship is
  operator-driven and rate-limited; the CAS-pin path is reserved as
  a Phase-3 slot (analogous to the schema-registry CAS-pin,
  Sprint-3 Tag-3). Sprint-5 Tag-2 ships PUT (LWW) only.~~ (**CONSUMED
  in Sprint-5 Tag-4** — the CAS-pin path `put_with_revision` is now
  the opt-in lost-update-protection surface, byte-mirroring the
  Phase-1b Sprint-3 Tag-3 schema-registry CAS-pin contract; see the
  "CAS-pin operational contract (Sprint-5 Tag-4)" subsection below.
  The Sprint-5 Tag-2 LWW `put` path remains supported and orthogonal
  to the CAS-pin path.)
- ~~This module does NOT modify the Sprint-5 Tag-1 publisher CLI. A
  future `--capability-bucket` flag that reads policies from this
  bucket is a Sprint-5 Tag-3+ candidate; Sprint-5 Tag-2 is the
  substrate, not the CLI integration.~~ (**CONSUMED in Sprint-5
  Tag-3** — the `--capability-bucket` flag now reads policies from
  this bucket via `NatsKvCapabilityPolicyBackend.snapshot_registry`,
  exposing the persistent-policy source on the operator surface
  end-to-end; see §5.13's "Bucket policy source (Sprint-5 Tag-3)"
  subsection. Sprint-5 Tag-2 substrate is consumed byte-unchanged.)
- This module does NOT modify `NatsKvSchemaRegistry`. The
  schema-registry backend (`wakir-schemas` bucket) is
  byte-unchanged.

#### Cross-Review-Zone-1 non-touched (all four Z-1-K-Sprint-4 points)

- **Z-1-K-Sprint-4-1 (kid-Resolver-Shape):** Sprint-5 Tag-2 does
  NOT import `kid_resolver`. The `allowed_kids` field on a
  persistent policy carries kid strings byte-equal to the in-process
  Sprint-4 Tag-6 bundle; resolver chain is upstream of the gate
  call.
- **Z-1-K-Sprint-4-2 (JCS-Resolver-Lock):** Sprint-5 Tag-2 does
  NOT canonicalise anything beyond the policy-envelope's
  sorted-keys JSON serialisation (which is not a JCS-anchored hash
  — there is no on-the-wire digest of the policy envelope analogous
  to `schema_body_sha256`). The Sprint-4 Tag-1 entry-signing path
  and its JCS canonicalisation are byte-unchanged.
- **Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519):** Sprint-5 Tag-2 is
  curve-agnostic. The persistent policy carries `allowed_kids`
  strings without a curve-axis; the Sprint-4 Tag-3 kid-resolver and
  Sprint-4 Tag-1 entry-signing primitives remain the curve-binding
  layer.
- **Z-1-K-Sprint-4-4 (STRICT-Mode-Activation-Owner):** Sprint-5
  Tag-2 is orthogonal to `VerifyMode`. The persistent-policy layer
  ships persistence, not signature verification.

#### Cross-Review-Zone-B paired-update (Kai-side action)

Sprint-5 Tag-2 IS a Zone-B trigger. The orchestrator-side
`PHASE_1_BUCKETS` inventory currently lists 6 slots
(post-Sprint-4 Tag-5):

| Slot | Name                              | Status                                    |
|------|-----------------------------------|-------------------------------------------|
| 0    | `wakir-schemas`                   | Live (Sprint-3 Tag-1 consumer)            |
| 1    | `wakir-aip-cache`                 | Live (AIP resolver)                       |
| 2    | `wakir-ftd-cache`                 | Live (FTD resolver)                       |
| 3    | `wakir-ftd-poisoned`              | Live (FTD poison-marker)                  |
| 4    | `wakir-schema-registry-entries`   | Phase-2 reservation (Sprint-4 Tag-4)      |
| 5    | `wakir-federation-routes`         | Live (V-908 consumer)                     |

Sprint-5 Tag-2 requests a 7th slot (`wakir-capability-policies`)
via the paired-update memo to the DevOps track
(`agents-workspaces/kai/inbox/2026-05-11-reza-z-b-seventh-bucket-capability-policies-paired-update.md`).
The Wirelang-side `BUCKET_CONFIG` is the byte-anchor; the
orchestrator-side `BucketSpec` will mirror it byte-precisely on
`history` / `ttl_seconds` / `max_value_size` / `storage` /
`replicas` on Kai-side acceptance (Sprint-5 Tag-3+ Kai-side slot).
The Wirelang-side consumer is byte-functional once the bucket is
materialised on the live cluster (operator-hand
`nats kv add wakir-capability-policies ...` or routine init-script
backfill — whichever the operator's chosen path).

#### Composition pattern (capability-policy lifecycle)

```python
# 1. Author publishes a policy to the bucket (one-time per
#    issuer / per policy-id):
from datetime import datetime, timezone
from wirelang.schemas.registered_by_capability import CapabilityPolicy
from wirelang.schemas.capability_policy_nats_kv_backend import (
    NatsKvCapabilityPolicyBackend,
    CapabilityPolicyRecord,
)

policy = CapabilityPolicy(
    registered_by="wirelang-eng",
    allowed_kids=("biscuit-root-1",),
    allowed_triples=(("wire", "layer-1-*"),),
    note="Tier-1 ingress signing policy",
)
record = CapabilityPolicyRecord(
    policy=policy,
    policy_id="tier-1-ingress",
    registered_at=datetime.now(timezone.utc),
    registered_by_publisher="wirelang-eng",
)

backend = NatsKvCapabilityPolicyBackend(kv=open_kv_handle)
await backend.put(record)

# 2. Verifier-side publisher (or gate consumer) materialises the
#    registry on startup or on a refresh schedule:
from wirelang.schemas.registered_by_capability import (
    check_registered_by_capability,
)

registry = await backend.snapshot_registry()
decision = check_registered_by_capability(
    entry, signature_block, registry, as_of=datetime.now(timezone.utc),
)
if not decision.allowed:
    raise RuntimeError(decision.reason)
```

The lifecycle is **two-process by design**: policy authorship and
schema-registry publication can run on different hosts. The
persistent bucket is the synchronisation point.

#### CAS-pin operational contract (Sprint-5 Tag-4, additive over Sprint-5 Tag-2)

Sprint-5 Tag-4 adds an opt-in lost-update-protection surface to the
persistent capability-policy backend. The substance is a
pattern-mirror on the Phase-1b Sprint-3 Tag-3 schema-registry
CAS-pin contract (see §5.4): identical typed-exception shape,
identical KV-adapter shim contract, identical determinism
invariants. The mirror is intentional — operators who already learn
the schema-registry CAS-pin idiom (`get_with_revision` →
`put_with_revision` → catch `*ConflictError` → re-read on conflict)
see the same idiom on the capability-policy layer, with the only
type-axis difference being the conflict exception class
(`SchemaRegistryConflictError` ↔ `CapabilityPolicyConflictError`).

**Why CAS-pin on capability-policy authorship.** The Sprint-5 Tag-2
LWW `put` path is acceptable when policy authorship is rare and
operator-coordinated (one operator hand-edits a policy at a time).
The CAS-pin path is the opt-in upgrade for concurrent-authorship
flows where two operators (or two automation pipelines) edit the
same `(registered_by, policy_id)` pair near-simultaneously — for
example to rotate `allowed_kids` after a key-rollover (one operator
adds the new kid; another revokes the old kid; without CAS-pin one
write overwrites the other silently). With CAS-pin the second
writer receives a `CapabilityPolicyConflictError`, re-reads the
current record, re-applies its intended edit on top, and re-tries.

**Read-modify-write loop:**

```python
from wirelang.schemas.capability_policy_nats_kv_backend import (
    NatsKvCapabilityPolicyBackend,
    CapabilityPolicyConflictError,
    CapabilityPolicyRecord,
)
from wirelang.schemas.registered_by_capability import CapabilityPolicy

backend = NatsKvCapabilityPolicyBackend(kv=open_kv_handle)

while True:
    got = await backend.get_with_revision_by_pair(
        "wirelang-eng", "tier-1-ingress"
    )
    if got is None:
        # First write: use LWW put (CAS create-if-absent is
        # adapter-dependent; see KV-adapter contract below).
        new_record = build_initial_record(...)
        await backend.put(new_record)
        break
    current_record, observed_revision = got
    new_record = mutate(current_record, ...)
    try:
        await backend.put_with_revision(new_record, observed_revision)
        break
    except CapabilityPolicyConflictError as exc:
        # A concurrent writer landed. Loop: re-read, re-apply,
        # re-try. The exception carries the live revision for
        # diagnostic surfacing.
        log.info(
            "policy CAS conflict on %s: expected=%s actual=%s; retrying",
            exc.key, exc.expected_revision, exc.actual_revision,
        )
        continue
```

**Validation-gate ordering (REQUIRED).** Identical to the
Sprint-3 Tag-3 schema-registry CAS-pin contract:

1. **Gate 1 — record type.** The `record` argument MUST be a
   `CapabilityPolicyRecord`. A non-record argument raises
   `TypeError` BEFORE any KV I/O. The bucket revision does not
   advance.
2. **Gate 2 — pair ↔ key derivation.** The
   `(record.policy.registered_by, record.policy_id)` pair derives
   the canonical key via `key_for_policy_pair`. A malformed pair
   would have been rejected by the `CapabilityPolicyRecord`
   `__post_init__` already (so the record could not have been
   constructed); the gate is a defence-in-depth re-check that
   ensures the record carries a derivable key before the CAS write.
3. **Gate 3 — non-negative expected-revision.** `expected_revision`
   MUST be a non-negative integer. Negative inputs raise
   `ValueError` BEFORE any KV I/O.

All three gates run BEFORE the revision-pin call. A malformed
record or invalid revision argument cannot leave the validation
surface even if the bucket revision happened to be stale.

**KV-adapter contract (3 shapes).** The
`_kv_update_with_revision` helper is byte-equal to the
schema-registry CAS-pin helper of the same name in
`wirelang.schemas.registry_nats_kv_backend`:

1. `kv.update(key, value, last=expected_revision)` — the canonical
   nats-py shape.
2. `kv.update(key, value, expected_revision)` — positional fallback
   for mocks that don't accept the `last` keyword.
3. `kv.put(key, value, expected_revision=...)` — keyword fallback
   for mocks that overload `put`.

A KV adapter that surfaces NONE of the three shapes raises
`CapabilityPolicyBackendError` with the message
`"CAS-pin not supported"`. Specifically the exception is NOT a
`CapabilityPolicyConflictError`: silent demotion to LWW would be a
correctness violation (the caller asked for CAS protection and got
LWW semantics without realising). T-CPP-CAS-10 anchors this
invariant.

**Conflict-exception class-name marker detection.** The helper
`_is_conflict_exception` recognises any exception whose class name
contains one of `WrongLastSequence`, `Conflict`, or
`RevisionMismatch`. This class-name marker is the same set as the
schema-registry CAS-pin helper. The marker-based detection keeps
the backend nats-py-version-agnostic: a future nats-py rename of
`KeyWrongLastSequenceError` to something else continues to be
detected as long as the new class name carries one of the markers
(and a backend test pin can be added at that point if not).

**Determinism contract (3 invariants).**

1. **Conflict-exception class-name detection.** The marker set
   `{"WrongLastSequence", "Conflict", "RevisionMismatch"}` is the
   recognised conflict-class-name set. A future-nats-py error class
   that introduces a new naming convention without one of these
   markers is NOT translated to `CapabilityPolicyConflictError` and
   propagates verbatim. T-CPP-CAS-aux-conflict-class-detection
   anchors this.
2. **Lost-update protection under bounded concurrency.** Given a
   starting revision `R0`, two writers observing `R0` and racing to
   `put_with_revision` produce exactly one winner and one
   conflict. The post-race revision is exactly `R0 + 1`. Extended
   to `N` interleaved pairs: exactly `N` winners and `N` conflicts;
   post-race revision is exactly `R0 + N`. T-CPP-CAS-08 and
   T-CPP-CAS-aux-determinism anchor this.
3. **CAS + LWW orthogonality.** A non-CAS `put` after a successful
   `put_with_revision` lands at the higher revision: the LWW path
   is byte-unchanged by the existence of the CAS path. The gate
   decision for the resulting policy is byte-equal regardless of
   which write path landed it. T-CPP-CAS-09 anchors this.

**Compatibility statement (Sprint-5 Tag-4 boundary).**

- Sprint-5 Tag-2 LWW surface (`put` / `get` / `get_by_pair` /
  `delete` / `list_keys` / `snapshot` / `snapshot_registry`) is
  byte-unchanged. T-CPP-01..10 from §6.11 remain green.
- Sprint-5 Tag-2 envelope (`wakir.wirelang.capability-policy-entry/1`
  on `wakir-capability-policies`) is byte-unchanged. M-2 conformance
  preserved.
- Sprint-5 Tag-2 bucket configuration (`BUCKET_CONFIG`) is
  byte-unchanged. `history=5` already supports CAS-pin (the
  underlying NATS-KV `update` operation is unconditional on history
  depth ≥ 1; the bucket history is independent of CAS semantics).
  Cross-Review-Zone-B non-touched; no new bucket; no new
  paired-update memo.
- The Phase-1b Sprint-3 Tag-3 schema-registry CAS-pin surface
  (`SchemaRegistryConflictError`, `NatsKvSchemaRegistry.get_with_revision`,
  `NatsKvSchemaRegistry.put_with_revision`) is byte-unchanged. The
  Sprint-5 Tag-4 capability-policy CAS-pin surface is a parallel
  module-local addition, not a refactor of the existing surface.
- The Phase-1c CAS-quorum slot (multi-replica CAS) remains reserved
  as a Phase-3 promotion slot for both modules.

#### Boundary: Sprint-5 Tag-4 does NOT ship (explicit)

- ~~A watch-stream tail on the capability-policy bucket (`watch()` /
  `WatchOp` / `LiveCapabilityPolicySnapshot`) — Phase-3 slot
  mirroring Sprint-3 Tag-4.~~ (**CONSUMED in Sprint-5 Tag-5** — the
  watch-stream tail `NatsKvCapabilityPolicyBackend.watch()` plus
  `CapabilityPolicyWatchOp` / `CapabilityPolicyWatchEvent` /
  `LiveCapabilityPolicySnapshot` ship in Tag-5; see the **Watch-stream
  operational contract** subsection below.)
- A `--capability-bucket-cas` CLI flag on the publisher CLI — the
  Sprint-5 Tag-3 `--capability-bucket` flag uses
  `snapshot_registry` (which never writes), so the CAS-pin path is
  reachable only via direct backend use today. Operator-CLI
  composition of the CAS-pin write path is a Sprint-5 Tag-5+
  candidate (likely a separate `wakir-capability-policy publish`
  subcommand surface) and explicitly NOT shipped in Tag-4.
- A CAS-quorum (multi-replica CAS) — Phase-3 slot. `replicas=1`
  Sprint-5 Tag-2 bucket configuration is unchanged; CAS-pin
  operates on the single-replica revision counter.
- A Biscuit v3 binary-token interpretation of the policy envelope —
  Phase-3 substrate; the in-bucket JSON envelope shape is
  Sprint-5 Tag-2 byte-unchanged.
- A mutation of `NatsKvSchemaRegistry` — the schema-registry
  backend is byte-unchanged.

#### Watch-stream operational contract (Sprint-5 Tag-5, additive over Sprint-5 Tag-4)

Phase-2 Sprint-5 Tag-4 shipped the CAS-pin write path on the
`wakir-capability-policies` bucket. Sprint-5 Tag-5 adds the live-tail
*read* path, mirroring the Phase-1b Sprint-3 Tag-4 schema-registry
watch-stream contract byte-precisely (with the predictable shift of
class identities and noun choices: `WatchOp` →
`CapabilityPolicyWatchOp`, `WatchEvent` → `CapabilityPolicyWatchEvent`,
`LiveSchemaSnapshot` → `LiveCapabilityPolicySnapshot`, `entry` →
`record` on the event payload).

**Why a watch-stream on capability-policies?** The Sprint-5 Tag-2 full
`snapshot_registry` path is correct for determinism but costly when
policy turnover is high (operator-side rotation campaigns rolling
`allowed_kids` across many policies under a single `registered_by`),
or when a long-running supervisor wants to track changes between
snapshots without re-listing. The watch-stream is the cheap
incremental layer: bootstrap once from a full
`NatsKvCapabilityPolicyBackend.snapshot`, then apply
`CapabilityPolicyWatchEvent` deltas as they arrive.

**Read-modify-watch loop** (operator-side supervisor pseudocode):

```python
# 1. Bootstrap the live view from a full snapshot.
live = await LiveCapabilityPolicySnapshot.from_backend(backend)

# 2. Open the watch-stream and apply incoming events. Per verifier
#    pass, hand a frozen registry to check_registered_by_capability.
async with await backend.watch() as stream:
    async for event in stream:
        live.apply(event)
        # Verifier pass on a stable snapshot:
        frozen_registry = live.as_registry()
        decision = check_registered_by_capability(
            entry, signature_block, frozen_registry, as_of=now
        )
```

**Async-iter contract.** The watch handle adapts to two underlying
watcher shapes (byte-equal to the Sprint-3 Tag-4 schema-registry
contract):

- **Shape 1:** the watcher is itself an async iterator
  (`__aiter__` / `__anext__`); `stop()` (sync or async) closes it.
- **Shape 2:** the watcher exposes `await updates()` returning the
  next update or `None` for end-of-stream; `stop()` closes it.

nats-py's real `KeyWatcher` matches Shape 2 with a sentinel `None`
between the initial snapshot replay and the live tail; the handle
surfaces this sentinel as a stream-internal marker only and does NOT
emit it to the consumer (T-CPP-WS-aux-async-iter Shape-1 probe and
T-CPP-WS-01 Shape-2 probe both cross-check this).

**Decoder contract.** `_decode_capability_policy_watch_update`
extracts:

- `operation` from the update's `operation` attribute (or mapping
  key) and normalises to upper-case; recognised values are `PUT`,
  `DELETE`, `PURGE`. An unknown operation raises
  `CapabilityPolicyEnvelopeError` (T-CPP-WS-07).
- `key` from `.key` (or mapping key); empty or non-string raises
  `CapabilityPolicyEnvelopeError`.
- `revision` from `.revision` (or mapping key); coerced to `int`,
  defaulting to `0` when absent.
- For `PUT`: the value bytes are extracted via
  `_coerce_value_bytes` and decoded through `_envelope_to_record`
  (the same path that backs `get` and `snapshot`); a poisoned
  envelope raises `CapabilityPolicyEnvelopeError`
  (T-CPP-WS-06).
- For `DELETE` / `PURGE`: `record` is set to `None`.

**Poison contract.** A decoder error raises
`CapabilityPolicyEnvelopeError` from the iterator and terminates it.
Operators must observe the error, drop the
`LiveCapabilityPolicySnapshot`, and re-bootstrap from a fresh
`NatsKvCapabilityPolicyBackend.snapshot`. Phase-2 Sprint-5 Tag-5 does
NOT silently swallow envelope poison (same contract as the full
`snapshot` path).

**Revision-monotonicity contract.** `LiveCapabilityPolicySnapshot.apply`
advances `last_revision` monotonically: an event with a revision
lower than the current `last_revision` does NOT regress the counter
(T-CPP-WS-08). The counter is useful for audit cross-references and
for future Phase-3 `resume_from` policies.

**Frozen-registry determinism contract.**
`LiveCapabilityPolicySnapshot.as_registry()` rebuilds a
`CapabilityPolicyRegistry` from a sorted-key view of the live
per-key map; the returned registry does not share storage with the
live state. Subsequent `apply()` calls do not mutate the returned
registry (T-CPP-WS-05). This is the determinism contract for
verifier passes against
`check_registered_by_capability`: a frozen copy passed to one
verifier pass yields stable verdicts, even as deltas arrive on the
stream during the pass.

**Orthogonality contract.** The watch-stream is a strict suffix of the
durable bucket history:

- A CAS-pin write (Sprint-5 Tag-4 `put_with_revision`) yields one PUT
  event on the stream identical to a LWW PUT.
- A LWW write (Sprint-5 Tag-2 `put`) yields one PUT event.
- A stale CAS-pin write rejected by the bucket yields NO event (the
  write was not durable; the bucket revision did not advance).

The gate decision is byte-equal regardless of how the registry was
materialised (`snapshot_registry` or watch-fed
`LiveCapabilityPolicySnapshot.as_registry`); T-CPP-WS-09 cross-checks
this against the Sprint-4 Tag-6 gate.

**Concurrency contract.** A `LiveCapabilityPolicySnapshot` is intended
for a single-consumer pattern within one asyncio task. Cross-task
sharing requires the caller to lock; the class itself does no
locking because asyncio guarantees in-task atomicity between
awaits, and `apply()` is synchronous.

**Internal storage rationale.** The
`LiveCapabilityPolicySnapshot._live` map is keyed by the full KV
key (`capability-policies/<registered_by>/<policy_id>`), not by
`registered_by` alone. This indirection is intentional: the
Sprint-4 Tag-6 `CapabilityPolicyRegistry` is indexed by
`registered_by` only (a single issuer may carry multiple policies);
the watch-stream needs per-`(issuer, policy_id)` update / delete
semantics so a DELETE event on `capability-policies/<issuer>/<id-A>`
does not nuke the issuer's other policies. `as_registry()` rebuilds
the `registered_by`-indexed view from the per-key map on each call.

#### Boundary: Sprint-5 Tag-5 does NOT ship (explicit)

- Watch-stream resumption / replay-from-revision
  (`watchall(..., resume_from=...)`) — Phase-3 slot. nats-py
  supports it; the Sprint-5 Tag-5 wrapper exposes the underlying
  revision via `CapabilityPolicyWatchEvent.revision` and
  `LiveCapabilityPolicySnapshot.last_revision` but does not bake in
  a resume policy.
- Publisher-CLI composition of the live-tail consumer (a
  `--capability-bucket-watch` flag or a daemon-mode subcommand on
  `wakir-publisher`) — Sprint-5 Tag-5+ candidate. The Sprint-5
  Tag-3 `--capability-bucket` flag remains a one-shot snapshot read
  (no watch-stream tail). Operators who want the live tail use the
  Python API directly (or a Sprint-5 Tag-6+ daemon).
- Multi-consumer fanout of a single underlying watcher — the
  per-task contract is sufficient for Phase-2; a Phase-3
  broadcast tier may layer on top.
- ~~A `Replicator`-style cross-bucket capability-policy replication
  (analogous to Sprint-3 Tag-6 schema-registry replication) —
  Phase-3 slot. Tag-5 lands the watch-stream substrate; the
  replication-tier composition is reserved.~~ **CONSUMED** in
  Phase-2 Sprint-6 Tag-6 (v0.19.0): see
  `wirelang/schemas/capability_policy_replication.py` and the
  v0.19.0 change-log entry. The Sprint-6 Tag-6 layer carries the
  Sprint-6 Tag-1 revocation-monotonic invariant byte-precisely
  across the cross-bucket boundary (a feature with no
  schema-registry-side analogue).
- A Biscuit v3 binary-token interpretation of the policy envelope —
  Phase-3 substrate; the in-bucket JSON envelope shape is
  Sprint-5 Tag-2 / Tag-4 byte-unchanged.
- A mutation of `NatsKvSchemaRegistry` — the schema-registry
  backend is byte-unchanged.

## 6. Test inventory

Phase-1b Sprint-3 Tag-1 ships hermetic tests at
`wirelang/tests/test_schema_registry_nats_kv_backend.py`. Inventory
T-SR-01..10 plus T-SR-aux probes:

- **T-SR-01:** `put` round-trips an entry through `get` (single-key
  semantics, identity-triple preserved).
- **T-SR-02:** `get` on an unknown key returns `None`.
- **T-SR-03:** `put` is last-write-wins for the same key.
- **T-SR-04:** `delete` removes an entry; subsequent `get` is `None`.
- **T-SR-05:** `snapshot` materialises an `InMemorySchemaRegistry`
  with all live entries.
- **T-SR-06:** a poisoned (non-JSON) value raises
  `SchemaRegistryEnvelopeError` from `get` and aborts `snapshot`.
- **T-SR-07:** envelope `schema` mismatch is rejected.
- **T-SR-08:** envelope `schema_id` ≠ `schema_body.$id` is rejected
  at write time.
- **T-SR-09:** envelope `schema_body_sha256` mismatch is rejected at
  write time.
- **T-SR-10:** bucket-config constants match the documented Phase-1
  inventory (drift-protection at the test layer).
- **T-SR-aux-determinism:** two back-to-back snapshots yield
  byte-equal `InMemorySchemaRegistry` keysets.
- **T-SR-aux-key-derivation:** `(layer, name, version)` ↔ key-string
  derivation is bijective.

Total: 10 primary determinism tests + 2 auxiliary probes = 12.

### 6.1 CAS-pin tests (Tag-3, additive over Tag-1)

Phase-1b Sprint-3 Tag-3 ships hermetic CAS-pin tests at
`wirelang/tests/test_schema_registry_cas_pin.py`. Inventory
T-SR-CAS-01..10 plus T-SR-CAS-aux probes:

- **T-SR-CAS-01:** `get_with_revision` round-trips an entry through
  `put_with_revision` (entry equality + revision monotonic).
- **T-SR-CAS-02:** `get_with_revision` on an unknown key returns
  `None` (no exception, mirrors `get` for absent keys).
- **T-SR-CAS-03:** `put_with_revision` succeeds when the
  `expected_revision` matches the live revision.
- **T-SR-CAS-04:** `put_with_revision` raises
  `SchemaRegistryConflictError` when the live revision has advanced
  (concurrent writer landed first). The error carries the observed
  `key`, `expected_revision`, and `actual_revision`.
- **T-SR-CAS-05:** Validation gate 1 (`schema_id` ↔ `$id`) runs
  BEFORE the CAS call; mismatch raises
  `SchemaRegistryValidationError` and the bucket revision does NOT
  advance.
- **T-SR-CAS-06:** Validation gate 2 (`schema_body_sha256`) runs
  BEFORE the CAS call; mismatch raises `SchemaRegistryValidationError`
  and the bucket revision does NOT advance.
- **T-SR-CAS-07:** `put_with_revision` rejects a negative
  `expected_revision` with `ValueError` (defence in depth).
- **T-SR-CAS-08:** Two interleaved CAS-pin loops on the same key:
  exactly one succeeds, the other receives
  `SchemaRegistryConflictError` with `actual_revision >
  expected_revision` (lost-update protection contract).
- **T-SR-CAS-09:** A successful `put_with_revision` followed by a
  non-CAS `put` is observable: the non-CAS `put` wins
  (last-write-wins for the LWW path; CAS-pin and LWW remain orthogonal).
- **T-SR-CAS-10:** A KV adapter without an `update` method falls
  through to `put(key, value, expected_revision=...)`; if the
  adapter does not accept that keyword either, the backend raises
  `SchemaRegistryBackendError` ("CAS-pin not supported"), not a
  silent demotion to LWW.

Auxiliary probes:

- **T-SR-CAS-aux-determinism:** ten back-to-back interleaved CAS-pin
  pairs over a single key yield a deterministic outcome: exactly
  five winners, five conflicts; the final revision is exactly five
  more than the starting revision (one increment per accepted
  writer).
- **T-SR-CAS-aux-conflict-class-detection:** the class-name marker
  detection (`_is_conflict_exception`) recognises
  `KeyWrongLastSequenceError`, `RevisionMismatchError`, and
  `KeyValueConflictError` and rejects unrelated exceptions like
  `ValueError`.

Total Tag-3 test additions: 10 primary CAS-pin tests + 2 auxiliary
probes = 12.

### 6.2 Watch-stream tests (Tag-4, additive over Tag-3)

Phase-1b Sprint-3 Tag-4 ships hermetic watch-stream tests at
`wirelang/tests/test_schema_registry_watch_stream.py`. Inventory
T-SR-WS-01..10 plus T-SR-WS-aux probes:

- **T-SR-WS-01:** `watch()` opens a stream and yields one decoded
  `WatchEvent` per upsert; events carry the correct `op` (`PUT`),
  `key`, `entry`, and `revision`.
- **T-SR-WS-02:** a DELETE on the bucket surfaces a DELETE
  `WatchEvent`; the `entry` field is `None`.
- **T-SR-WS-03:** `LiveSchemaSnapshot.from_backend` bootstraps from
  a full snapshot; subsequent `apply(PUT)` updates the live state.
  An entry present in the bootstrap is preserved.
- **T-SR-WS-04:** `LiveSchemaSnapshot.apply(DELETE)` removes the
  key from the live state.
- **T-SR-WS-05:** A frozen `InMemorySchemaRegistry` returned from
  `as_registry()` does NOT mutate when subsequent `apply()` calls
  arrive. The frozen copy preserves the entry-set at the moment of
  the call. (Determinism contract, the Tag-4 invariant for verifier
  passes.)
- **T-SR-WS-06:** A poisoned watch update (non-JSON `value` on
  `PUT`) raises `SchemaRegistryEnvelopeError` from the iterator and
  terminates the stream.
- **T-SR-WS-07:** An update with an unrecognised `operation` kind
  raises `SchemaRegistryEnvelopeError`.
- **T-SR-WS-08:** `LiveSchemaSnapshot.last_revision` advances
  monotonically with each applied event; an out-of-order earlier-
  revision event does NOT regress the counter.
- **T-SR-WS-09:** A frozen registry from a watch-fed `LiveSchemaSnapshot`
  exposes `lookup` / `lookup_by_triple` / `keys_sorted` consistent
  with a fresh full-bucket snapshot from `backend.snapshot()`. Cross-
  reference T-SR-05 (full snapshot path).
- **T-SR-WS-10:** `open_watch_stream` rejects a non-`NatsKvSchemaRegistry`
  argument with `TypeError`.

Auxiliary probes:

- **T-SR-WS-aux-async-iter:** the watch handle is async-iter
  compatible with the Shape-1 (native `__aiter__` / `__anext__`)
  watcher mock. The nats-py end-of-initial-replay `None` sentinel is
  filtered at the handle layer (consumers do NOT see it).
- **T-SR-WS-aux-purge-removes:** a `WatchOp.PURGE` event removes the
  key from the live state identically to `DELETE`.

Total Tag-4 test additions: 10 primary watch-stream tests + 2
auxiliary probes = 12.

### 6.3 Publisher CLI tests (Tag-5, additive over Tag-4)

Phase-1b Sprint-3 Tag-5 ships hermetic publisher-CLI tests at
`wirelang/tests/test_schema_registry_publisher_cli.py`. Inventory
T-SR-PUB-01..12:

- **T-SR-PUB-01:** parser shape — `publish` and `dry-run` are both
  registered subcommands; required flags missing → exit 2; the
  `--create-only` / `--expected-revision` mutual-exclusion is
  enforced at the argparse layer.
- **T-SR-PUB-02:** `dry-run` happy path — receipt JSON has the stable
  schema; `mode` is "dry-run"; `key` is `schemas/<layer>/<name>/<version>`;
  `schema_body_sha256` matches a fresh `schema_body_sha256` over the
  body; `revision` is `null`; stderr is empty.
- **T-SR-PUB-03:** `publish` (LWW) — no CAS flags; the bucket gains
  exactly one entry; receipt `mode` is "lww"; `revision >= 1`;
  `expected_revision` is `null`; stderr is empty.
- **T-SR-PUB-04:** `publish --expected-revision N` (CAS-pin) — the
  supplied `N` matches live revision; CAS publish succeeds; receipt
  `mode` is "cas"; `expected_revision` echoes `N`; the new
  `revision` is exactly `N + 1`.
- **T-SR-PUB-05:** `publish --expected-revision N` (CAS-pin conflict)
  — `N` is stale; exit 5 (CAS_CONFLICT); error envelope on stderr;
  bucket state is byte-equal to the pre-call snapshot (no mutation
  on a failed CAS).
- **T-SR-PUB-06:** `publish --create-only` (success) — entry absent;
  bucket gains revision 1; receipt `mode` is "create-only";
  `expected_revision` is `0`; `revision` is `1`.
- **T-SR-PUB-07:** `publish --create-only` (conflict) — entry already
  present; exit 5; error envelope on stderr; bucket revision NOT
  advanced past the seed.
- **T-SR-PUB-08:** input error — `--schema-body` path does not exist;
  exit 3 (INPUT_ERROR); error envelope on stderr; bucket untouched.
- **T-SR-PUB-09:** input error — `--schema-body` is not valid JSON;
  exit 3; error envelope mentions the JSON parse failure; bucket
  untouched.
- **T-SR-PUB-10:** validation error — `schema_body` has no `$id`
  field; CLI gate raises `SchemaRegistryValidationError`; exit 4
  (VALIDATION_ERROR); bucket untouched.
- **T-SR-PUB-11:** validation error — `--registered-by` is whitespace-
  only; CLI gate raises `SchemaRegistryValidationError`; exit 4;
  bucket untouched.
- **T-SR-PUB-12:** stdout / stderr separation — on success, stdout
  carries exactly one line of valid JSON and stderr is empty; on
  failure, stderr carries exactly one line of valid JSON and stdout
  is empty.

Total Tag-5 test additions: 12 hermetic determinism tests
(T-SR-PUB-01..12). The CLI's `_default_connect_factory` is NOT
exercised at the test layer (it would require a live NATS cluster);
production operators verify it manually against their local cluster.

### 6.4 Replication tests (Tag-6, additive over Tag-5)

Phase-1b Sprint-3 Tag-6 ships hermetic replication tests at
`wirelang/tests/test_schema_registry_replication.py`. Inventory
T-SR-REP-01..12:

- **T-SR-REP-01:** bootstrap copies every source entry onto an empty
  target in keys-sorted order; `bootstrap_applied` advances by the
  number of source entries; the target's keyset is byte-equal to
  the source's keyset post-bootstrap.
- **T-SR-REP-02:** a second bootstrap pass on a byte-equal target
  is a no-op via the `bootstrap_skipped_idempotent` counter
  (idempotency contract; the second-pass `bootstrap_applied` is 0
  because the new metrics object starts fresh).
- **T-SR-REP-03:** a `ReplicationFilter` skips entries that do not
  match a layer constraint during the bootstrap pass; the
  filtered-out entry is NOT written to the target;
  `bootstrap_skipped_by_filter` advances.
- **T-SR-REP-04:** live PUT events on the source land on the target
  via the watch-stream tail; `events_applied_put` advances per event.
- **T-SR-REP-05:** a live DELETE on the source removes the entry
  from the target via the watch-stream tail; `events_applied_delete`
  advances.
- **T-SR-REP-06:** under `ReplicationConflictPolicy.CAS_PIN`, a
  target-side mutation that lands between the replicator's
  read-revision and CAS-pinned-write surfaces as a CAS conflict
  on the underlying backend; the replicator catches it, increments
  `cas_conflicts`, and continues with subsequent events. The
  replicator does NOT overwrite the target's out-of-band state.
- **T-SR-REP-07:** `halt_on_conflict=True` re-raises
  `SchemaRegistryConflictError` on the first CAS conflict;
  `cas_conflicts` is incremented before re-raise.
- **T-SR-REP-08:** a poisoned envelope on the source watch-stream
  (non-JSON `value` on a PUT update) halts `run` with
  `SchemaRegistryEnvelopeError`; `envelope_errors` is 1.
- **T-SR-REP-09:** a `ReplicationFilter` that returns `SKIP` on a
  live PUT event prevents the event from reaching the target;
  `events_skipped_by_filter` advances.
- **T-SR-REP-10:** the `SchemaReplicator` constructor rejects
  source==target with `ValueError` (no self-replication contract).
- **T-SR-REP-11:** a malformed PUT `WatchEvent` arriving with
  `entry=None` (handcrafted, bypassing the decoder) is rejected at
  the replicator's apply boundary as
  `SchemaRegistryEnvelopeError` (defence-in-depth).
- **T-SR-REP-12:** `run(bootstrap=False)` skips the bootstrap pass;
  the pre-existing source entry is NOT pre-loaded onto the target,
  but the live tail events still land. Bootstrap counters stay 0
  while live counters advance.

Total Tag-6 test additions: 12 hermetic determinism tests
(T-SR-REP-01..12). The replication module does NOT establish NATS
connections itself; tests inject the same in-memory `_MockKv` shape
used by Tag-3 / Tag-4 / Tag-5, with a wrapper that simulates the
read-then-mutate race window for the CAS-conflict path.

### 6.5 Entry-signing tests (Phase-2 Sprint-4 Tag-1, additive over Tag-6)

Phase-2 Sprint-4 Tag-1 ships hermetic entry-signing tests at
`wirelang/tests/test_schema_registry_entry_signing.py`. Inventory
T-SR-SIG-01..12:

- **T-SR-SIG-01:** `sign_entry` → `verify_entry_signature` round-trip
  on a freshly-generated Ed25519 key-pair returns `True`. The
  returned `SignedSchemaRegistryEntry` carries the original entry
  byte-equal (`entry == returned.entry`).
- **T-SR-SIG-02:** signing is deterministic over the JCS canonical
  form: two `SchemaRegistryEntry` instances with byte-equal envelopes
  produce identical pre-image SHA-256 digests. (Ed25519 itself is
  deterministic per RFC 8032; equality of the digest is the
  necessary-and-sufficient invariant.)
- **T-SR-SIG-03:** the signature block is structurally fixed:
  `{alg: "Ed25519", kid: <given>, signature: <128-hex>}`. Any
  deviation (missing field, wrong alg, malformed hex, wrong length)
  raises `SchemaRegistrySignatureError` from
  `verify_entry_signature`.
- **T-SR-SIG-04:** tamper detection — mutating any envelope field
  on a signed entry (layer / name / version / schema_id /
  schema_body / schema_body_sha256 / registered_at /
  registered_by / supersedes) and re-running `verify_entry_signature`
  with the same signature block returns `False`.
- **T-SR-SIG-05:** self-reference exclusion — modifying the
  `signature` field of the envelope does NOT change the signing
  pre-image. The signature slot is stripped before JCS
  canonicalisation.
- **T-SR-SIG-06:** `envelope_with_signature` emits the envelope
  bytes that round-trip through `envelope_to_signed_entry` to a
  byte-equal `SignedSchemaRegistryEntry`. The optional `signature`
  slot is the only difference versus the Tag-1 codec.
- **T-SR-SIG-07:** backward compatibility — a v0.5.0-style envelope
  WITHOUT a `signature` slot round-trips through
  `envelope_to_signed_entry` and returns a plain
  `SchemaRegistryEntry` (parity with the Tag-1 codec).
- **T-SR-SIG-08:** `PERMISSIVE` mode — an unsigned envelope (no
  `signature` slot) verifies as `True` via
  `verify_entry_signature(entry, mode=PERMISSIVE)`. A signed envelope
  is verified end-to-end.
- **T-SR-SIG-09:** `STRICT` mode — an unsigned envelope raises
  `SchemaRegistrySignatureError` with a missing-signature message
  via `verify_entry_signature(entry, mode=STRICT)`.
- **T-SR-SIG-10:** wrong public key — `verify_entry_signature` with
  a different Ed25519 public key on a validly-signed entry returns
  `False` (cryptographic failure, not structural).
- **T-SR-SIG-11:** wrong key length — supplying a non-32-byte
  public key or non-32-byte private key raises a
  `SchemaRegistrySignatureError` (structural).
- **T-SR-SIG-12:** Tag-1 codec parity — a signed envelope emitted by
  `envelope_with_signature` is byte-equal to the corresponding
  unsigned Tag-1 envelope EXCEPT for the one optional `signature`
  slot. Stripping the slot from the signed envelope and re-decoding
  through the Tag-1 codec recovers the original entry byte-equal
  (the Tag-1 codec is unchanged in Sprint-4 Tag-1).

Total Phase-2 Sprint-4 Tag-1 test additions: 12 hermetic determinism
tests (T-SR-SIG-01..12). The signing layer is pure: no NATS
connections, no I/O. Tests use `cryptography.hazmat.primitives.
asymmetric.ed25519` to generate ephemeral key-pairs from
deterministic 32-byte seeds and known-answer Ed25519 vectors where
applicable.

### 6.6 kid-resolver tests (Phase-2 Sprint-4 Tag-3, additive over Sprint-4 Tag-1)

Phase-2 Sprint-4 Tag-3 ships hermetic resolver tests at
`wirelang/tests/test_identity_kid_resolver.py`. Inventory
T-KID-RES-01..12:

- **T-KID-RES-01** — happy-path resolve through the wired
  `generate_aip_document` factory. Pins that the resolver agrees with
  the byte-shape the generator emits: `kid="biscuit-root-1"`,
  `alg="Ed25519"`, `purpose="biscuit-root"`, validity-window parsed.
- **T-KID-RES-02** — multi-key resolve. Two distinct kids in
  `public_keys` (`biscuit-root-1` + `aip-signing-1`), both Ed25519,
  resolve independently to the right key.
- **T-KID-RES-03** — cross-layer end-to-end. Sign a
  `SchemaRegistryEntry` with `entry_signing.sign_entry`; resolve the
  kid via `resolve_kid`; feed the resolved public key into
  `verify_entry_signature(..., mode=VerifyMode.STRICT)`. Pins that
  the composition pattern (§5.9) verifies under STRICT. Negative
  branch: a wrong-key resolve returns `False` from verify (crypto
  failure, not structural).
- **T-KID-RES-04** — kid-not-found structural failure. A kid absent
  from `public_keys` raises `KidResolverError` with a
  `"kid not found"` message; the error message includes the list of
  candidate kids.
- **T-KID-RES-05** — duplicate-kid structural failure. Two
  `public_keys` entries with the same `kid` raise `KidResolverError`
  with a `"duplicate kid"` message; the resolver refuses to silently
  pick a winner.
- **T-KID-RES-06** — wrong-alg filter. A `secp256k1` entry on the
  requested kid raises `KidResolverError` (`"alg is not 'Ed25519'"`).
  Reinforces Z-1-K-Sprint-4-3: secp256k1 entries are invisible to
  the Identity-Document signing-layer resolver.
- **T-KID-RES-07** — validity-window enforcement. Three sub-cases
  with the same `validafter`/`validuntil` window: `as_of` before
  window raises `"not yet valid"`; inside window resolves
  successfully; after window raises `"has expired"`. A fourth probe
  confirms that no `as_of` argument disables the window check
  (historical-signature use-case).
- **T-KID-RES-08** — purpose-filter enforcement. `require_purpose`
  matching the entry passes; mismatched purpose raises
  `"purpose mismatch"`.
- **T-KID-RES-09** — malformed `key_hex` structural failures
  (three sub-cases): wrong hex-string length (62 chars); correct
  length but non-hex characters; missing `key_hex` field entirely.
  All three raise `KidResolverError`.
- **T-KID-RES-10** — missing/malformed `public_keys` array (five
  sub-cases): missing field; non-sequence (dict); a string in place
  of the sequence (Python sees strings as sequences — the resolver
  excludes `str`/`bytes` explicitly); empty array; non-mapping
  `aip_doc` argument; plus an empty-kid argument probe.
- **T-KID-RES-11** — `list_resolvable_kids` filter behaviour.
  Asserts: no filters lists both kids in sorted order; window filter
  excludes the expired key; purpose filter narrows to one kid;
  wrong-alg entries are dropped; duplicate kids cause both copies
  to be dropped (returns empty list when both kids of a 2-entry
  document collide).
- **T-KID-RES-12** — determinism. Repeated `resolve_kid` calls on
  the same input produce equal `ResolvedPublicKey` instances
  (frozen-dataclass equality); a JSON round-trip on the AIP document
  does not affect the result; `list_resolvable_kids` is also
  order-deterministic.

Total Phase-2 Sprint-4 Tag-3 test additions: 12 hermetic determinism
tests (T-KID-RES-01..12). The resolver is pure: no transport,
no signature verification on the AIP document, no I/O. Tests use
RFC 8032 Ed25519 test-vector seeds and hand-crafted minimal AIP-
document fragments.

**Suite-level effect (post-Sprint-4 Tag-3):** the wirelang test
suite grows from 671 passed (post-Sprint-4 Tag-1) to **683 passed**
(+12 net). The Tag-1 entry-signing tests (T-SR-SIG-01..12) remain
unchanged and green.

### 6.7 AIP-document transport-fetch tests (Phase-2 Sprint-4 Tag-4, additive over Sprint-4 Tag-3)

Phase-2 Sprint-4 Tag-4 ships hermetic transport-fetch tests at
`wirelang/tests/test_aip_document_transport_fetch.py`. Inventory
T-AIP-FT-01..12. All tests are hermetic: a fake `urlopen` is injected
into `HTTPSDocumentTransport` and a stub `TxtResolver` is supplied
for the DNS-anchor path. No real HTTPS calls and no real DNS queries
leave the process.

- **T-AIP-FT-01** — `aip_web_to_https_url` canonical mappings. Four
  sub-cases: `aip:web:host/persona-path` → canonical URL; no-path
  `aip:web:host` → `index.json` under `.well-known/aip/`; trailing
  `.json` on persona-path is stripped (single-source canonical form);
  pre-resolved `https://...` URL passes through verbatim.
- **T-AIP-FT-02** — URL-scheme structural failures. Six sub-cases:
  empty string; bare `aip:web:`; `aip:web:` with empty-host; `did:web:`
  (wrong scheme); plaintext `http://` (rejected with a V-908 §3.3
  message); bare `https://`. All six raise `AipUrlSchemeError`.
- **T-AIP-FT-03** — happy-path HTTPS fetch without DNS-anchor.
  `fetch_aip_document` returns an `AipFetchResult` with correct
  `aip_id`/`url`/`host`/`aip_doc`/`body_bytes`/`jcs_sha256_hex` and
  `dns_anchor=None`, `anchor_matched=False`. Exactly one HTTPS call
  at the mapped URL.
- **T-AIP-FT-04** — V-908 transport error propagation. A `404` from
  the fake `urlopen` surfaces as `HTTPSStatusError` (V-908 §3.3
  invariant), not as an `AipDocumentTransportError`; the typed
  `.status == 404` access is preserved (no wrapping).
- **T-AIP-FT-05** — non-object root body. A JSON array (`[1,2,3]`)
  as the body raises `HTTPSPayloadError` (the V-908 transport
  enforces "JSON object root"; the Tag-4 defensive guard is dead
  code in the production wire and is pinned to the transport here).
- **T-AIP-FT-06** — DNS-anchor soft-match. `anchor_required=False`
  with a matching TXT record (`v=1; sha256=<fp>` where `fp` equals
  the local JCS-anchor hex) → `anchor_matched=True`, `dns_anchor`
  populated, exactly one DNS resolver call at `_wakir-aip.<host>`
  with the configured timeout.
- **T-AIP-FT-07** — DNS-anchor soft-absent. `anchor_required=False`
  with no TXT record at the anchor host → no raise; `dns_anchor=None`,
  `anchor_matched=False`. The soft mode swallows the underlying
  `DnsAnchorError`.
- **T-AIP-FT-08** — DNS-anchor hard-mismatch. `anchor_required=True`
  with a TXT record whose fingerprint disagrees with the local
  JCS-anchor hex → `AipDnsAnchorMismatchError` with `expected` set
  to the local hex and `observed` set to the wire hex; `host` and
  `aip_id` carried on the exception.
- **T-AIP-FT-09** — DNS-anchor hard-absent. `anchor_required=True`
  with no TXT record at the anchor host → `AipDnsAnchorMismatchError`
  with a `"lookup failed"` message; the underlying `DnsAnchorError`
  is chained via `__cause__`.
- **T-AIP-FT-10** — eager-raise on missing resolver.
  `anchor_required=True` with `dns_resolver=None` → `AipDnsAnchorMismatchError`
  with `"dns_resolver is None"`. The HTTPS fetch still occurs (the
  eager raise happens post-fetch; the contract documents this).
- **T-AIP-FT-11** — cross-layer composition. End-to-end:
  `fetch_aip_document` → `resolve_kid`. The fetched body produces a
  `ResolvedPublicKey` whose `public_key` byte-equals the RFC-8032
  Ed25519 test-vector public key seeded into the AIP-doc fixture.
  Pairs with Sprint-4 Tag-3 `T-KID-RES-03` (the resolver →
  `verify_entry_signature` half) to pin the canonical Phase-2
  verifier flow.
- **T-AIP-FT-12** — determinism and pre-resolved-URL pass-through.
  Repeated `fetch_aip_document` calls with the same `aip_id` and
  byte-equal response produce byte-equal `(url, host, aip_doc,
  jcs_sha256_hex)`. The `https://...` pre-resolved shape produces
  the same `jcs_sha256_hex` as the `aip:web:` shape on the same body
  (URL passes through; host is parsed identically).

Total Phase-2 Sprint-4 Tag-4 test additions: 12 hermetic determinism
tests (T-AIP-FT-01..12). The fetcher is pure-composition: no signature
verification, no schema validation, no caching. Tests use a fake
`urlopen` script + a stub `TxtResolver` for end-to-end determinism;
RFC 8032 Ed25519 test-vector seeds are reused from the Sprint-4 Tag-3
kid-resolver tests for the cross-layer composition probe.

**Suite-level effect (post-Sprint-4 Tag-4):** the wirelang test
suite grows from **683 passed** (post-Sprint-4 Tag-3) to **695 passed**
(+12 net). The Tag-1 entry-signing tests (T-SR-SIG-01..12) and the
Tag-3 kid-resolver tests (T-KID-RES-01..12) remain unchanged and
green.

### 6.8 AIP-document signature-verification cache tier tests (Phase-2 Sprint-4 Tag-5, additive over Sprint-4 Tag-4)

Phase-2 Sprint-4 Tag-5 ships hermetic verification-cache tests at
`wirelang/tests/test_aip_signature_verification_cache.py`. Inventory
T-AIP-SVC-01..12. All tests are hermetic: no real time (an
injectable `_FakeClock` provides deterministic monotonic ticks),
no I/O, no transport, no NATS. The Ed25519 signing primitive runs
in-process via the existing `cryptography` dependency; RFC 8032
test-vector seeds 1 and 2 are reused from the Sprint-4 Tag-3 / Tag-4
test fixtures.

- **T-AIP-SVC-01** — construction and defaults. Default
  construction yields `max_entries=DEFAULT_MAX_ENTRIES=256` and
  `ttl_seconds=DEFAULT_TTL_SECONDS=300.0`. Initial stats are all
  zero. Bad-arg-grid: `max_entries <= 0` and `ttl_seconds <= 0`
  both raise `ValueError` with documented messages.
- **T-AIP-SVC-02** — hit on second verify; outcome byte-equal to
  fresh. First `cache.verify(...)` is a miss (`stats.misses == 1`,
  `stats.size == 1`); second call with byte-equal inputs is a hit
  (`stats.hits == 1`, `stats.misses` unchanged). The hit outcome
  is byte-equal (`is`-identity for the Boolean) to a fresh
  `verify_aip_signature` call.
- **T-AIP-SVC-03** — TTL-based invalidation. A `_FakeClock` walks
  the cache window. At `t=9.999s < 10s ttl`, the second lookup is
  a hit. At `t=10.001s > 10s ttl`, the third lookup is a miss-via-
  expiry: the `expired` counter increments AND `misses` increments;
  `hits` does NOT. After the re-insertion, the cache still has one
  entry (the freshly re-inserted one at `t=10.001`), not two.
- **T-AIP-SVC-04** — LRU eviction in insertion order. Three
  distinct `(doc, sig, pub)` triples in a 2-slot cache. After
  insert-A + insert-B, a *hit* on A does NOT promote A (insertion-
  order LRU, hit-does-not-promote contract). Inserting C evicts
  A; a re-verify of A is a miss that evicts B (`evictions == 2`);
  a re-verify of B is a miss that evicts C (`evictions == 3`).
- **T-AIP-SVC-05** — negative caching. Sign with priv_A, verify
  against pub_B → `False`. The first call is a miss; the second
  call is a hit returning `False`. The cached negative outcome is
  byte-equal to a fresh `verify_aip_signature(... pub_B)` call.
- **T-AIP-SVC-06** — cache-key construction distinctness across
  all 5 components. Five probes — body, alg, kid, signature_hex,
  pub_key — each producing a distinct cache key. Reflexivity:
  byte-equal inputs produce byte-equal keys.
- **T-AIP-SVC-07** — cache-key `KeyError` on malformed
  `signature_block`. Missing `alg` / `kid` / `signature` each
  raises `KeyError(f"missing {field}")` from the cache-key
  function (the underlying verifier would also raise
  `ValueError`; the cache distinguishes the two failure modes).
- **T-AIP-SVC-08** — structural failures NOT cached. A
  `signature_block` with `alg="Ed448"` raises `ValueError` from
  the underlying verifier. The cache propagates the exception
  verbatim; `stats.size` stays at `0`; `stats.misses` and
  `stats.hits` are unchanged. A repeat call raises the same
  `ValueError` (deterministic) without producing a cache entry.
- **T-AIP-SVC-09** — `evict_expired()` bulk sweep. Two entries
  inserted at `t=0`. Within TTL (`t=9s`), the sweep is a no-op.
  Past TTL (`t=10.5s > 10s ttl`), the sweep removes both;
  `expired` counter rises by 2; `size == 0`.
- **T-AIP-SVC-10** — `document_signature` slot stripped before
  cache-key body digest. Two documents that differ only in their
  attached `document_signature` slot produce the same cache key
  (the cache key is bound to the body content, not to whatever
  signature was attached at fetch time). The `_jcs_body_digest_hex`
  helper is also byte-equal across the two documents.
- **T-AIP-SVC-11** — `clear()` drops entries but preserves
  lifetime counters. After miss + hit, `clear()` empties the cache
  (`size == 0`) but `hits` / `misses` / `evictions` / `expired`
  survive. A repeat verify after `clear()` is a miss (the cache
  was emptied).
- **T-AIP-SVC-12** — free-function `cached_verify_aip_signature`
  routes through the supplied cache. Two calls via the free
  function produce a miss followed by a hit on the same cache; the
  function is byte-equivalent to `cache.verify(...)`. Calling
  `cache.verify(...)` directly after the free-function form
  registers a second hit. The free-function outcome is byte-equal
  to a fresh `verify_aip_signature` call. `CacheStats` is a
  defensive copy: mutating the returned snapshot does NOT mutate
  the live cache counters.

Total Phase-2 Sprint-4 Tag-5 test additions: 12 hermetic determinism
tests (T-AIP-SVC-01..12). The cache is a pure performance
optimisation: no signature verification logic, no schema validation,
no transport-fetch coupling. Tests use an injectable `_FakeClock`
for hermetic TTL determinism; RFC 8032 Ed25519 test-vector seeds
are reused from the Sprint-4 Tag-3 / Tag-4 fixtures.

**Suite-level effect (post-Sprint-4 Tag-5):** the wirelang test
suite grows from **695 passed** (post-Sprint-4 Tag-4) to **707 passed**
(+12 net). The Tag-1 entry-signing tests (T-SR-SIG-01..12), the
Tag-3 kid-resolver tests (T-KID-RES-01..12) and the Tag-4
transport-fetch tests (T-AIP-FT-01..12) remain unchanged and green.

### 6.9 `registered_by`-capability-gating tests (Phase-2 Sprint-4 Tag-6, additive over Sprint-4 Tag-5)

Phase-2 Sprint-4 Tag-6 ships hermetic capability-gating tests at
`wirelang/tests/test_registered_by_capability.py`. Inventory
T-RBC-01..12. All tests are hermetic: no real time, no I/O, no
transport, no NATS. Datetime arguments use timezone-aware UTC
instances; the Ed25519 signing primitive (for the T-RBC-10
composition test) runs in-process via the existing `cryptography`
dependency with RFC 8032 test-vector seed 1.

- **T-RBC-01** — construction defaults and bad-arg-grid. Minimal
  `CapabilityPolicy` constructs with `not_before=None`,
  `not_after=None`, `disabled=False`, `note=None`. A 10-row
  parametrised bad-arg-grid covers empty `registered_by`, empty
  `allowed_kids`, empty kid-string, empty `allowed_triples`,
  malformed triple shape (wrong arity, empty name), non-datetime
  `not_before`, non-datetime `not_after`, non-bool `disabled`, and
  non-string `note`. A separate test pins the inverted-window
  rejection (`not_before >= not_after` raises
  `RegisteredByCapabilityError` with a "strictly less than"
  message fragment).
- **T-RBC-02** — matching policy yields `POLICY_MATCH` allow. The
  decision carries the matched policy by reference; the policy's
  `note` field round-trips unchanged.
- **T-RBC-03** — unknown `registered_by` and empty-registry both
  yield `NO_POLICY_FOR_ISSUER` deny with `policy=None`. The
  audit-string `reason` contains the unknown identity fragment.
- **T-RBC-04** — kid not in `allowed_kids` yields
  `KID_NOT_ALLOWED` deny; the reason string carries both the
  presented kid and the `allowed_kids` tuple. A separate test pins
  the multi-policy iteration: two policies under the same issuer
  with disjoint `allowed_kids`; the gate iterates and finds the
  second policy that carries the presented kid.
- **T-RBC-05** — triple not covered by `allowed_triples` yields
  `TRIPLE_NOT_ALLOWED` deny on both the layer dimension (entry
  `layer-2-semantic` vs policy `layer-1-wire`) and the name
  dimension (entry `audit-trail-leaf` vs policy `frame-envelope`).
- **T-RBC-06** — layer wildcard `"*"` matches any layer. A
  `("*", "frame-envelope")` policy allows both
  `layer-1-wire/frame-envelope` and `layer-2-semantic/frame-envelope`.
  A `("*", "*")` policy allows any triple including a novel
  layer-9-novel/exotic-shape probe.
- **T-RBC-07** — name glob fnmatch. A `("layer-1-wire", "frame-*")`
  policy allows `frame-envelope` and `frame-burst` but denies
  `audit-trail`. A `("layer-1-wire", "frame-?")` (single-char glob)
  policy allows `frame-a` but denies `frame-ab`.
- **T-RBC-08** — disabled policy is invisible to the allow path.
  A registry that only carries disabled policies for an issuer
  returns `POLICY_DISABLED` deny. A registry with both a disabled
  and a non-disabled policy yields `POLICY_MATCH` allow.
- **T-RBC-09** — validity-window enforcement. A policy with
  `[not_before=2026-06-01, not_after=2026-07-01)` denies a gate
  call with `as_of=2026-05-01` (before-window) and
  `as_of=2026-07-01` (exclusive after-window bound), and allows
  `as_of=2026-06-15` (inside window). Omitting `as_of` bypasses
  the window check entirely.
- **T-RBC-10** — `gate_signed_entry` end-to-end composition with
  `sign_entry`. A real Ed25519-signed
  `SignedSchemaRegistryEntry` flows into the gate; a matching
  policy yields `POLICY_MATCH` allow; an unauthorised issuer
  yields `NO_POLICY_FOR_ISSUER` deny. Passing a bare
  `SchemaRegistryEntry` (not a signed wrapper) raises
  `RegisteredByCapabilityError`.
- **T-RBC-11** — decision dataclass shape and structural-failure
  arg-grid. `CapabilityGateDecision` is frozen
  (attribute-assignment raises); equality is by value. The gate
  call rejects a non-`SchemaRegistryEntry` `entry`, a
  non-mapping `signature_block`, a `signature_block` missing
  `kid`, a non-`CapabilityPolicyRegistry` registry, a non-datetime
  `as_of`, and an empty `kid` string — each raises
  `RegisteredByCapabilityError`.
- **T-RBC-12** — `CapabilityPolicyRegistry.list_issuers` and
  `policies_for` contract. `list_issuers` returns a sorted tuple
  snapshot. `policies_for` returns a defensive tuple snapshot;
  subsequent `add_policy` calls do NOT mutate earlier snapshots
  but DO appear in fresh snapshots. `add_policy` rejects non-policy
  input with `RegisteredByCapabilityError`. The deny-precedence
  ordering is pinned: a registry with one policy denying by kid
  followed by a policy denying by triple yields a final
  `TRIPLE_NOT_ALLOWED` source (the higher-precedence deny replaces
  the lower-precedence one in the audit log).

Total Phase-2 Sprint-4 Tag-6 test additions: 12 hermetic test
classes (T-RBC-01..12); 45 individual test functions when counting
the parametrised bad-arg-grid and per-scenario sub-tests. The gate
is a pure-function authorisation tier: no signature verification
logic, no schema validation, no transport-fetch coupling, no clock
dependency outside the explicit `as_of` argument.

**Suite-level effect (post-Sprint-4 Tag-6):** the wirelang test
suite grows from **707 passed** (post-Sprint-4 Tag-5) to **752 passed**
(+45 net). The Tag-1 entry-signing tests (T-SR-SIG-01..12), the
Tag-3 kid-resolver tests (T-KID-RES-01..12), the Tag-4
transport-fetch tests (T-AIP-FT-01..12), and the Tag-5
verification-cache tests (T-AIP-SVC-01..12) remain unchanged and
green.

### 6.10 Publisher-CLI capability integration tests (Phase-2 Sprint-5 Tag-1, additive over Sprint-4 Tag-6)

Phase-2 Sprint-5 Tag-1 ships hermetic tests at
`wirelang/tests/test_publisher_cli_capability_integration.py`. The
inventory is **T-SR-PUB-CG-01..10** plus an auxiliary
loader-helper coverage class. Tests are hermetic: no NATS, no real
transport, no real DNS, no wall-clock dependency for receipt
determinism (`--registered-at` is supplied; the Ed25519 seed is the
RFC 8032 test-vector 1 32-byte seed).

- **T-SR-PUB-CG-01:** capability-registry JSON loader — single
  policy round-trip; optional `not_before` / `not_after` parsed to
  UTC; multi-policy registration preserves FIFO; missing `policies`
  array rejected with `TypeError`; non-object policy entry rejected
  with `TypeError` carrying `policies[<i>]`; missing required key
  (e.g. `registered_by`) rejected with `TypeError`. 6 sub-tests.

- **T-SR-PUB-CG-02:** `--sign` happy path (LWW publish) — receipt
  carries `signed=True`, `kid="biscuit-root-1"`, `gate_decision=None`;
  bucket holds the canonical entry envelope at the expected key;
  separately, a signature-verify round-trip with the same seed/kid
  succeeds under `VerifyMode.STRICT`. 2 sub-tests.

- **T-SR-PUB-CG-03:** `--sign --gate` happy path — POLICY_MATCH on
  a single-policy registry. Receipt has both `signed=True` and
  `gate_decision.allowed=True` with `source="policy_match"`; bucket
  revision advances by exactly 1.

- **T-SR-PUB-CG-04:** `--gate` deny on unknown `registered_by` —
  exit 7 (`CAPABILITY_DENY`); JSON error envelope on stderr carries
  `error=CAPABILITY_DENY`, `exit_code=7`, and a message containing
  `no_policy_for_issuer`; bucket NOT touched (`store == {}`,
  `revision == 0`).

- **T-SR-PUB-CG-05:** `--gate` deny on disallowed `kid` — exit 7;
  message contains `kid_not_allowed`; bucket NOT touched.

- **T-SR-PUB-CG-06:** `--gate` deny on triple mismatch — two
  sub-tests pin the layer-mismatch and name-glob-mismatch axes
  separately; each exits 7 with `triple_not_allowed`; bucket NOT
  touched. 2 sub-tests.

- **T-SR-PUB-CG-07:** flag-consistency rejection — `--gate` without
  `--sign` exits 3 with `--gate requires --sign`;
  `--capability-registry` without `--gate` exits 3 with the orphan
  flag message; bucket NOT touched in either case. 2 sub-tests.

- **T-SR-PUB-CG-08:** sign-flag-consistency rejection — `--sign`
  without `--kid` exits 3; `--sign` without a key source exits 3;
  orphan `--kid` without `--sign` exits 3; both key sources
  together fail at the argparse mutex layer with `SystemExit(2)`.
  4 sub-tests.

- **T-SR-PUB-CG-09:** dry-run with `--sign --gate` — allow path
  produces a receipt with `mode="dry-run"`, `signed=True`,
  `revision=null`, and an allow `gate_decision`; deny path on
  dry-run also exits 7. 2 sub-tests.

- **T-SR-PUB-CG-10:** receipt-shape forward-compat — bare publish
  emits a receipt with `signed=false`, `kid=null`,
  `gate_decision=null`; all pre-Sprint-5 fields remain present;
  bare dry-run mirrors the same defaults. 2 sub-tests.

- **Auxiliary loader-helper coverage** (`TestAuxLoaderHelpers`):
  `_load_ed25519_priv_key` accepts a 64-hex string, a 32-byte
  binary file, and a 64-hex ASCII file; rejects malformed-hex
  inputs with `ValueError`; `_validate_capability_flag_consistency`
  is a no-op for an all-default Namespace. 5 sub-tests.

**Suite-level effect (post-Sprint-5 Tag-1):** the wirelang test
suite grows from **752 passed** (post-Sprint-4 Tag-6) to
**780 passed, 1 skipped, 7 subtests passed** (+28 net through the
T-SR-PUB-CG-01..10 family and auxiliary coverage). The Sprint-3
Tag-5 publisher-CLI inventory (T-SR-PUB-01..12) and the Sprint-4
Tag-6 capability-gating inventory (T-RBC-01..12) remain unchanged
and green; the Sprint-5 Tag-1 tests are additive and exercise a
parallel test module.

#### Bucket policy source tests (Phase-2 Sprint-5 Tag-3, additive)

Sprint-5 Tag-3 ships hermetic tests at
`wirelang/tests/test_publisher_cli_capability_bucket.py`. The
inventory is **T-SR-PUB-CB-01..10** plus an auxiliary
`TestAuxBucketLoader` class. Tests are hermetic: no NATS, no real
transport, no real DNS, no wall-clock dependency for receipt
determinism (`--registered-at` is supplied; the Ed25519 seed is the
RFC 8032 test-vector 1 32-byte seed; both backends use in-memory
mocks `_MockKvCas` for the schema-registry bucket and
`_MockKvCapability` for the capability-policy bucket).

- **T-SR-PUB-CB-01:** bucket loader happy path — a single
  `CapabilityPolicyRecord` seeded on the in-memory
  `_MockKvCapability` round-trips through
  `NatsKvCapabilityPolicyBackend.snapshot_registry` into the
  `CapabilityPolicyRegistry` the gate consumes. Receipt carries
  `signed=true`, `gate_policy_source="bucket"`,
  `gate_decision.allowed=true`, `gate_decision.source="policy_match"`.

- **T-SR-PUB-CB-02:** `--sign --gate --capability-bucket` happy path
  (LWW publish) — receipt `mode="lww"`, `revision=1`,
  `gate_policy_source="bucket"`; the schema bucket holds the
  canonical entry envelope and `schema_kv.revision == 1`.

- **T-SR-PUB-CB-03:** `--capability-bucket` deny on unknown
  `registered_by` — the bucket holds a policy for a different issuer.
  Exit 7 (`CAPABILITY_DENY`); JSON error envelope carries
  `no_policy_for_issuer`; schema bucket NOT touched
  (`store == {}`, `revision == 0`).

- **T-SR-PUB-CB-04:** `--capability-bucket` deny on disallowed `kid`
  — bucket policy allows only `biscuit-root-2`; signing uses
  `biscuit-root-1`. Exit 7 with `kid_not_allowed`; schema bucket NOT
  touched.

- **T-SR-PUB-CB-05:** `--capability-bucket` deny on triple mismatch
  — bucket policy allows only `semantic` layer; publish targets
  `wire`. Exit 7 with `triple_not_allowed`; schema bucket NOT touched.

- **T-SR-PUB-CB-06:** mutex between `--capability-registry` and
  `--capability-bucket` — argparse `add_mutually_exclusive_group`
  enforcement; supplying both raises `SystemExit(2)`; no factory is
  ever invoked.

- **T-SR-PUB-CB-07:** orphan `--capability-bucket` without `--gate`
  — `_validate_capability_flag_consistency` rejects; exit 3
  (`INPUT_ERROR`) with message containing `--capability-bucket` and
  `require --gate`. Schema bucket NOT touched.

- **T-SR-PUB-CB-08:** poisoned bucket envelope (non-JSON value on a
  valid-looking bucket key) raises `CapabilityPolicyEnvelopeError`
  from the loader; the CLI routes it through `ExitCode.VALIDATION_ERROR
  = 4`; schema bucket NOT touched.

- **T-SR-PUB-CB-09:** dry-run with `--sign --gate --capability-bucket`
  — allow path produces a receipt with `mode="dry-run"`,
  `signed=true`, `revision=null`, `gate_policy_source="bucket"`, and
  an allow `gate_decision`. Empty-bucket deny path on dry-run also
  exits 7. 2 sub-tests.

- **T-SR-PUB-CB-10:** cross-source byte-equality — for an operator
  who stages byte-identical policies under both
  `--capability-registry` (JSON file) and `--capability-bucket`
  (NATS-KV bucket), the resulting receipts differ ONLY in the
  `gate_policy_source` field (`"file"` vs. `"bucket"`); all other
  fields including `gate_decision`, `kid`, `signed`, `key`,
  `schema_body_sha256`, `registered_at`, and `revision` are
  byte-equal.

- **Auxiliary bucket-loader coverage** (`TestAuxBucketLoader`):
  factory's `_cleanup` callback is invoked on the happy path;
  `_cleanup` is also invoked when `snapshot_registry` raises (poisoned
  envelope); multi-policy bucket preserves sorted-key snapshot order
  (the gate consumes policies in `(registered_by, policy_id)`
  sort order). 3 sub-tests.

**Suite-level effect (post-Sprint-5 Tag-3):** the wirelang test
suite grows from **804 passed, 1 skipped, 7 subtests passed**
(post-Sprint-5 Tag-2) to **818 passed, 1 skipped, 7 subtests passed**
(+14 net through the T-SR-PUB-CB-01..10 family and the auxiliary
class). The Sprint-3 Tag-5 publisher-CLI inventory
(T-SR-PUB-01..12), the Sprint-4 Tag-6 capability-gating inventory
(T-RBC-01..12), the Sprint-5 Tag-1 inventory (T-SR-PUB-CG-01..10),
and the Sprint-5 Tag-2 inventory (T-CPP-01..10) remain unchanged and
green; the Sprint-5 Tag-3 tests are additive and exercise a parallel
test module.

### 6.11 Capability-policy persistent distribution tests (Phase-2 Sprint-5 Tag-2, additive over Sprint-5 Tag-1)

Sprint-5 Tag-2 ships hermetic tests at
`wirelang/tests/test_capability_policy_nats_kv_backend.py`. The
inventory mirrors the Sprint-3 Tag-1
`test_schema_registry_nats_kv_backend.py` structure (T-CPP-01..10 +
auxiliary probes):

- **T-CPP-01:** `put` round-trips a `CapabilityPolicyRecord` through
  `get`; the embedded `CapabilityPolicy` field equality is asserted
  byte-precisely; `get_by_pair(registered_by, policy_id)` returns the
  same record (convenience helper).
- **T-CPP-02:** `get` on an unknown key returns `None`;
  `get_by_pair` on an absent pair returns `None`.
- **T-CPP-03:** `put` is last-write-wins for the same
  `(registered_by, policy_id)` pair; the second put's
  `allowed_kids`, `allowed_triples`, and `note` overwrite the first;
  the mock revision counter advances to `2`.
- **T-CPP-04:** `delete` removes the record; subsequent `get`
  returns `None`; subsequent `delete` is a no-op (tombstoned;
  idempotent).
- **T-CPP-05:** `snapshot` materialises a sorted-by-key list of
  records (3 records across 2 issuers in the fixture);
  `snapshot_registry` materialises a `CapabilityPolicyRegistry`
  with the right `list_issuers()` set and the right
  `policies_for(issuer)` cardinalities (the
  multi-policy-per-issuer case is exercised explicitly).
- **T-CPP-06:** a poisoned (non-JSON) value raises
  `CapabilityPolicyEnvelopeError` from `get` and aborts `snapshot`;
  the determinism contract requires complete, self-consistent
  snapshots.
- **T-CPP-07:** a value with the wrong `schema` field is rejected
  with `CapabilityPolicyEnvelopeError` whose message mentions
  `schema mismatch`.
- **T-CPP-08:** bucket-config constants are byte-stable
  (drift-protection at the test layer): `BUCKET_NAME`,
  `BUCKET_CONFIG[name]`, `BUCKET_CONFIG[history]=5`,
  `BUCKET_CONFIG[ttl_seconds]=0`,
  `BUCKET_CONFIG[max_value_size]=16_384`,
  `BUCKET_CONFIG[storage]="file"`, `BUCKET_CONFIG[replicas]=1`,
  `VALUE_SCHEMA`, plus the `Phase-2` substring in the description.
- **T-CPP-09:** a multi-policy-per-issuer bucket (two policies for
  `wirelang-eng`, one with `(wire, layer-1-*)`, one with
  `(identity, *)`) round-trips through `snapshot_registry` into a
  registry where the Sprint-4 Tag-6 gate
  (`check_registered_by_capability`) allows both triple sets
  (`POLICY_MATCH` source) and denies a federation-side triple with
  `TRIPLE_NOT_ALLOWED`. This is the end-to-end persistence ↔
  gate-evaluation byte-anchor.
- **T-CPP-10:** two back-to-back `snapshot` calls over the same
  bucket state yield byte-equal sorted-key lists and byte-equal
  envelope blobs per record (`_record_to_envelope` produces stable
  bytes).
- **`TestAuxKeyDerivation`** (auxiliary probes):
  `key_for_policy_pair` ↔ `pair_for_key` round-trip across four
  representative issuer / policy_id shapes; empty components
  rejected; slashes in components rejected; invalid characters
  (spaces) rejected; malformed keys (wrong prefix, too few
  components, too many components) rejected; non-string inputs
  rejected.
- **`TestAuxEnvelopeShape`** (auxiliary probes): missing required
  field rejected (`allowed_kids`); `allowed_triples` shape errors
  (object instead of array, 3-element inner array, ...) rejected;
  `disabled` must be a strict boolean (string `"false"` rejected);
  empty `allowed_kids` rejected via the Sprint-4 Tag-6
  `CapabilityPolicy` constructor's invariants (wrapped through to
  `CapabilityPolicyEnvelopeError`); `CapabilityPolicyRecord`
  rejects a naive (tz-unaware) `registered_at` at construction.

**Suite-level effect (post-Sprint-5 Tag-2):** the wirelang test
suite grows from **780 passed** (post-Sprint-5 Tag-1) to
**804 passed, 1 skipped, 7 subtests passed** (+24 net through the
T-CPP-01..10 family and the two auxiliary classes). The Sprint-3
Tag-1 schema-registry-backend inventory (T-SR-01..10 + 2 aux), the
Sprint-4 Tag-6 capability-gating inventory (T-RBC-01..12), and the
Sprint-5 Tag-1 publisher-CLI-capability-integration inventory
(T-SR-PUB-CG-01..10 + aux) all remain unchanged and green; the
Sprint-5 Tag-2 tests are additive and exercise a parallel test
module.

### 6.12 Capability-policy CAS-pin tests (Phase-2 Sprint-5 Tag-4, additive over Sprint-5 Tag-3)

Sprint-5 Tag-4 ships hermetic tests at
`wirelang/tests/test_capability_policy_cas_pin.py`. The inventory
is a **pattern-mirror** on the Phase-1b Sprint-3 Tag-3
`test_schema_registry_cas_pin.py` structure (T-SR-CAS-01..10 + 2
auxiliary probes). The mirror is byte-precise on test-shape; the
only differences are the substrate module under test
(`capability_policy_nats_kv_backend` vs. `registry_nats_kv_backend`)
and the typed exception class
(`CapabilityPolicyConflictError` vs. `SchemaRegistryConflictError`).

- **T-CPP-CAS-01:** `get_with_revision` round-trips the record and
  its KV revision; the revision matches the one returned from
  `put`. `get_with_revision_by_pair` returns byte-equivalent result.
- **T-CPP-CAS-02:** `get_with_revision` for an absent key returns
  `None`; `get_with_revision_by_pair` for an absent pair returns
  `None`; a malformed pair (empty `registered_by`) also returns
  `None` (graceful degradation, no raise — mirrors `get_by_pair`
  semantics).
- **T-CPP-CAS-03:** `put_with_revision` succeeds when
  `expected_revision == live_revision`. The updated record is
  observable via `get_with_revision` at the new revision. The
  scenario is a key-rollover: `allowed_kids = ("biscuit-root-1",)`
  → `("biscuit-root-1", "biscuit-root-2")` via CAS-pin.
- **T-CPP-CAS-04:** `put_with_revision` raises
  `CapabilityPolicyConflictError` on stale `expected_revision`. The
  error carries `key`, `expected_revision`, and `actual_revision`
  (the CAS-mock surfaces the live revision). The bucket-revision
  anchor is verified: `kv.revision` is unchanged from the rejected
  stale write.
- **T-CPP-CAS-05:** gate-1 (record-type) runs BEFORE the CAS call.
  A non-`CapabilityPolicyRecord` argument raises `TypeError`; the
  bucket revision does NOT advance.
- **T-CPP-CAS-06:** gate-2 (pair ↔ key derivation) runs BEFORE the
  CAS call. The Sprint-5 Tag-2 `CapabilityPolicyRecord`
  `__post_init__` rejects a malformed `policy_id` (slashes
  forbidden); the record cannot be constructed in the first place,
  so the bucket revision does NOT advance from any
  `put_with_revision` attempt.
- **T-CPP-CAS-07:** negative `expected_revision` raises
  `ValueError`. Defence in depth.
- **T-CPP-CAS-08:** interleaved CAS pair: two writers observing
  the same starting revision race to `put_with_revision`; exactly
  one wins, the other receives `CapabilityPolicyConflictError` with
  `actual_revision > expected_revision`. The lost-update protection
  contract.
- **T-CPP-CAS-09:** CAS+LWW orthogonality: a non-CAS `put` after a
  successful `put_with_revision` lands as LWW. The Tag-2 LWW path
  is byte-unchanged by the existence of the CAS path.
  `get_with_revision` returns the LWW record at the higher
  revision.
- **T-CPP-CAS-10:** a KV adapter without an `update` method and
  without a `put(expected_revision=...)` keyword path raises
  `CapabilityPolicyBackendError` with message
  `"CAS-pin not supported"`. Specifically NOT a
  `CapabilityPolicyConflictError` (no silent LWW demotion).

- **T-CPP-CAS-aux-determinism:** 5-pair interleaved CAS-pin pairs
  over a single key yield exactly 5 winners and 5 conflicts; the
  final revision is exactly `starting_revision + 5` (one increment
  per accepted writer). Anchors the determinism contract under
  bounded concurrency.
- **T-CPP-CAS-aux-conflict-class-detection:** the class-name marker
  detection (`_is_conflict_exception`) recognises typical nats-py
  conflict exception class names (`KeyWrongLastSequenceError`,
  `KeyValueConflictError`, `RevisionMismatchError`) and rejects
  unrelated classes (`ValueError`, generic `Exception`,
  `UnrelatedError`).

**Suite-level effect (post-Sprint-5 Tag-4):** the wirelang test
suite grows from **818 passed, 1 skipped, 7 subtests passed**
(post-Sprint-5 Tag-3) to **830 passed, 1 skipped, 7 subtests
passed** (+12 net through the T-CPP-CAS-01..10 family and the two
auxiliary probes). The Sprint-3 Tag-3 schema-registry CAS-pin
inventory (T-SR-CAS-01..10 + 2 aux), the Sprint-5 Tag-2
capability-policy LWW inventory (T-CPP-01..10 + 2 aux), and the
Sprint-5 Tag-3 publisher-CLI bucket-source inventory
(T-SR-PUB-CB-01..10 + aux) all remain unchanged and green; the
Sprint-5 Tag-4 tests are additive and exercise a parallel test
module.

### 6.13 Capability-policy watch-stream tests (Phase-2 Sprint-5 Tag-5, additive over Sprint-5 Tag-4)

Phase-2 Sprint-5 Tag-5 ships hermetic tests at
`wirelang/tests/test_capability_policy_watch_stream.py`. Inventory
T-CPP-WS-01..10 plus 2 auxiliary probes (byte-precise pattern-mirror
on the Sprint-3 Tag-4 schema-registry watch-stream test inventory at
`wirelang/tests/test_schema_registry_watch_stream.py`, with class
identities shifted to the capability-policy module):

- **T-CPP-WS-01:** `watch()` opens a stream and yields decoded PUT
  events. Two records are written to a freshly-watched bucket; the
  stream surfaces two PUT events with the correct `key`, `record`,
  and `revision` fields, in put-order.
- **T-CPP-WS-02:** a DELETE on the bucket surfaces a DELETE
  `CapabilityPolicyWatchEvent`; the event's `record` is `None`. PUTs
  issued *before* the watcher is open are NOT surfaced (the watcher
  binds to the live tail; the bootstrap path is
  `LiveCapabilityPolicySnapshot.from_backend`).
- **T-CPP-WS-03:** `LiveCapabilityPolicySnapshot.from_backend`
  bootstraps from a full snapshot; subsequent `apply(PUT)` updates
  the live state. Verified via the `records()` accessor on the live
  view (stable sorted-key order).
- **T-CPP-WS-04:** `LiveCapabilityPolicySnapshot.apply(DELETE)`
  removes the key from the live state; `records()` reflects the
  removal.
- **T-CPP-WS-05:** `LiveCapabilityPolicySnapshot.as_registry()`
  returns a frozen copy; subsequent `apply()` calls do NOT mutate
  the returned registry. Determinism contract for verifier passes.
  Two registries — one frozen, one current — are taken across an
  intervening apply, and only the current registry reflects the
  delta (the frozen registry has the bootstrap state only).
- **T-CPP-WS-06:** a poisoned watch update (non-JSON value on PUT)
  raises `CapabilityPolicyEnvelopeError` from the iterator and
  terminates it. The poison is hand-pushed onto the mock watcher to
  bypass the put-helper (which would have rejected the bad value at
  write time).
- **T-CPP-WS-07:** an update with an unrecognised `operation` kind
  raises `CapabilityPolicyEnvelopeError`. Cross-reference T-CPP-WS-06:
  the watch-stream poison contract is symmetric across value-level
  and operation-level malformation.
- **T-CPP-WS-08:** `LiveCapabilityPolicySnapshot.last_revision`
  advances monotonically and never regresses. Three events applied
  with revisions `5`, `10`, `3` (in that order) leave
  `last_revision = 10`.
- **T-CPP-WS-09:** a frozen registry from a watch-fed snapshot gates
  identically to the full-snapshot path against the Sprint-4 Tag-6
  `check_registered_by_capability` gate. Cross-reference T-CPP-04
  (full snapshot_registry). A `SchemaRegistryEntry` is constructed
  with `registered_by="wirelang-eng"`, `layer="wire"`,
  `name="layer-1-wire"`; a `signature_block` carries
  `kid="biscuit-root-1"`; both registries (watch-fed and
  full-snapshot) return `allowed=True` from the gate.
- **T-CPP-WS-10:** `open_capability_policy_watch_stream` rejects a
  non-backend argument with `TypeError`. Defence in depth against
  caller-side type confusion.
- **T-CPP-WS-aux-async-iter:** the watch handle is async-iter
  compatible with the Shape-1 (native `__aiter__` / `__anext__`)
  watcher. Cross-reference T-CPP-WS-01 (Shape-2 contract). Two
  events plus an intervening `None` sentinel are pre-loaded; the
  handle yields exactly two `CapabilityPolicyWatchEvent` instances
  (the sentinel is filtered out at the handle layer).
- **T-CPP-WS-aux-purge-removes:** a PURGE
  `CapabilityPolicyWatchEvent` removes the key from the live state
  identically to DELETE. The two operations are surfaced as distinct
  enum values (so audit consumers can distinguish them) but their
  effect on `LiveCapabilityPolicySnapshot._live` is identical.

**Suite-level effect.** `wirelang/tests/` was 830 passing before
Sprint-5 Tag-5; Sprint-5 Tag-5 brings the count to **842** (+12
net). The Sprint-3 Tag-4 schema-registry watch-stream inventory
(T-SR-WS-01..10 + 2 aux), the Sprint-5 Tag-2 capability-policy LWW
inventory (T-CPP-01..10 + 2 aux), the Sprint-5 Tag-3 publisher-CLI
bucket-source inventory (T-SR-PUB-CB-01..10 + aux), and the
Sprint-5 Tag-4 capability-policy CAS-pin inventory
(T-CPP-CAS-01..10 + 2 aux) all remain unchanged and green; the
Sprint-5 Tag-5 tests are additive and exercise a parallel test
module.

### 6.14 Capability-policy revocation tests (Phase-2 Sprint-6 Tag-1, additive over Sprint-5 Tag-5)

Phase-2 Sprint-6 Tag-1 ships hermetic tests at
`wirelang/tests/test_capability_policy_revocation.py`. Inventory
T-CPP-REV-01..10 plus 2 auxiliary probes; all twelve are green at
the Sprint-6 Tag-1 tip:

- **T-CPP-REV-01:** `CapabilityPolicy` admits `revoked_at` (tz-aware
  datetime) and `revocation_reason` (string); unrevoked defaults
  preserved. A naive (tz-unaware) `revoked_at` is rejected.
- **T-CPP-REV-02:** `revocation_reason` set without `revoked_at` is
  structurally invalid and raises `RegisteredByCapabilityError` at
  the bundle constructor.
- **T-CPP-REV-03:** the gate denies with
  `DecisionSource.POLICY_REVOKED` when `as_of >= revoked_at` (both
  exact-match and strictly-after). The decision's `reason` includes
  the `revoked_at` instant and the `revocation_reason` text.
- **T-CPP-REV-04:** the gate evaluates normally when
  `as_of < revoked_at` — revocation has not yet taken effect; a
  policy that would otherwise match returns
  `DecisionSource.POLICY_MATCH`.
- **T-CPP-REV-05:** the gate denies with `POLICY_REVOKED` even when
  `as_of=None`. Revocation is categorical and never silently
  bypassed by a verifier that omits a clock. Cross-reference T-RBC-09
  (Sprint-4 Tag-6 window semantics): the validity-window check
  *does* skip on `as_of=None` (intentional, documented bypass); the
  revocation check does *not* (intentional asymmetry).
- **T-CPP-REV-06:** revocation outranks `POLICY_DISABLED` /
  `KID_NOT_ALLOWED` / `TRIPLE_NOT_ALLOWED` /
  `OUTSIDE_VALIDITY_WINDOW` in the fallback-source ordering. Three
  policies are registered for one issuer (one revoked, one with
  kid-mismatch, one disabled); regardless of insertion order, the
  final deny carries `source=POLICY_REVOKED` and references the
  revoked policy.
- **T-CPP-REV-07:** the on-the-wire envelope round-trips
  `revoked_at` and `revocation_reason` byte-equally via
  `_record_to_envelope` / `_envelope_to_record`. The serialised
  JSON carries both keys; the decoded record carries the same
  tz-aware datetime (UTC-normalised, `Z` suffix).
- **T-CPP-REV-08:** an older Sprint-5 Tag-2..5 envelope (omitting
  the two new keys entirely) decodes via the Sprint-6 Tag-1 decoder
  to an unrevoked policy. Back-compat is byte-precise; the
  envelope-additive contract is verified.
- **T-CPP-REV-09:** `put_with_revision` enforces the un-revoke
  veto. A revoked record at the key, followed by a CAS-pinned write
  with `revoked_at=None`, raises
  `CapabilityPolicyRevocationConflict` with `existing_revoked_at`
  set to the live instant and `proposed_revoked_at=None`. The live
  KV revision is unchanged after the rejection.
- **T-CPP-REV-10:** `put_with_revision` admits the equal-instant
  idempotent rewrite. A revoked record, followed by a CAS-pinned
  write with the *same* `revoked_at` but a refreshed
  `revocation_reason`, advances the live revision by one and is
  observable via `get`. Audit-trail refresh remains legal.
- **T-CPP-REV-aux-advance-rejected:** `put_with_revision` rejects an
  attempt to advance `revoked_at` strictly later than the live
  instant. Revocation cannot be retroactively softened; the
  exception carries both instants for downstream audit.
- **T-CPP-REV-aux-lww-allows-unrevoke:** the Sprint-5 Tag-2 LWW
  `put` path does NOT enforce revocation-monotonicity. An operator
  who deliberately calls `put` (not `put_with_revision`) with an
  unrevoked record against a revoked live state can un-revoke; the
  revocation event remains in the bucket history depth for audit.
  Cross-reference T-CPP-REV-09: the safety invariant lives on the
  CAS-pin path, consistent with the Sprint-5 Tag-4 rationale.

**Suite-level effect.** `wirelang/tests/` was 842 passing before
Sprint-6 Tag-1; Sprint-6 Tag-1 brings the count to **854** (+12
net). The Sprint-4 Tag-6 `registered_by`-capability-gating
inventory (T-RBC-01..12), the Sprint-5 Tag-2 capability-policy LWW
inventory (T-CPP-01..10 + 2 aux), the Sprint-5 Tag-3 publisher-CLI
bucket-source inventory (T-SR-PUB-CB-01..10 + aux), the Sprint-5
Tag-4 CAS-pin inventory (T-CPP-CAS-01..10 + 2 aux) and the
Sprint-5 Tag-5 watch-stream inventory (T-CPP-WS-01..10 + 2 aux) all
remain unchanged and green; the Sprint-6 Tag-1 tests are additive
and exercise a parallel test module.

## 7. Cross-references and Open-Items

- V-908 backend pattern source:
  `wirelang/federation/route_registry_nats_kv_backend.py`.
- V-908 conflict-error pattern source:
  `RouteRegistryConflictError` in the same module (Tag-3 mirror).
- V-908 watch-stream pattern source: Tag-6 `WatchOp` / `WatchEvent` /
  `LiveSnapshot.from_backend` / `_MockWatcher` in the same module
  (Tag-4 mirror).
- Bucket inventory source:
  `scripts/init-nats-buckets.py` `PHASE_1_BUCKETS[0]` (`wakir-schemas`).
- **Phase-1c CAS-pin: OI-7-Phase-1c-CAS — CONSUMED in Tag-3.**
- **Phase-1c watch-stream: OI-7-Phase-1c-watch — CONSUMED in Tag-4.**
- **Phase-1c publisher CLI: OI-7-Phase-1c-publisher — CONSUMED in
  Tag-5.** Module: `wirelang/schemas/publisher_cli.py`. Tests:
  `wirelang/tests/test_schema_registry_publisher_cli.py`.
- **Phase-1c cross-bucket replication: OI-7-Phase-1c-replication
  — CONSUMED in Tag-6.** Module: `wirelang/schemas/replication.py`.
  Tests: `wirelang/tests/test_schema_registry_replication.py`.
- **Phase-1c is feature-complete; all four Phase-1c slots are
  consumed (Tag-3 / Tag-4 / Tag-5 / Tag-6).**
- **Phase-2 entry-signing: OI-7-Phase-2-sig — CONSUMED in Sprint-4
  Tag-1.** Module: `wirelang/schemas/entry_signing.py`. Tests:
  `wirelang/tests/test_schema_registry_entry_signing.py`. Signing
  primitive reuses `wirelang/identity/aip_signing.py` JCS+SHA-256+
  Ed25519 byte-identical (Cross-Review-Zone-1 Identity-Substrate
  touch).
- **Phase-2 kid → public-key resolver: CONSUMED in Sprint-4 Tag-3.**
  Module: `wirelang/identity/kid_resolver.py`. Tests:
  `wirelang/tests/test_identity_kid_resolver.py` (T-KID-RES-01..12).
  Closes Z-1-K-Sprint-4-1 (kid-Resolver-Shape) and reinforces
  Z-1-K-Sprint-4-3 (Curve-Choice = Ed25519). The resolver is the
  Identity-Substrate consumer of Sprint-4 Tag-1 signature blocks:
  callers feed `resolved.public_key` into `verify_entry_signature`
  (§5.9 composition pattern).
- Phase-2 CAS-quorum: **OI-7-Phase-2-quorum** (reserved).
- Phase-2 deprecation policy: **OI-7-Phase-2-deprecation** (reserved).
- Phase-2 IPFS schema-hash: **OI-7-Phase-2-ipfs** (reserved).
- Phase-2 bidirectional replication: **OI-7-Phase-2-bidir-replication**
  (reserved; CRDT-style merge contract for two-way mirror).
- Phase-2 watch-stream resume: **OI-7-Phase-2-resume** (reserved;
  resume-from-revision policy on connection drop).
- **Phase-2 AIP-document transport-fetch: CONSUMED in Sprint-4
  Tag-4.** Module: `wirelang/identity/aip_document_transport_fetch.py`.
  Tests: `wirelang/tests/test_aip_document_transport_fetch.py`
  (T-AIP-FT-01..12). Closes the Sprint-4 Tag-3 §5.9 boundary item
  "AIP-document transport-fetch (`did:web` / `aip:web` HTTPS bridge)".
  The module composes the V-908 Phase-1b HTTPS-transport
  (`HTTPSDocumentTransport`) and the V-908 §3.4 DNS-anchor pattern
  (extended from FTD-doc to AIP-doc via the parallel TXT-record
  prefix `_wakir-aip.<host>`; same `v=1; sha256=<64-hex>` format).
  The fetch layer is byte-orthogonal to AIP-document signature
  verification (`wirelang.identity.verify_aip_signature` unchanged),
  the kid-resolver (Tag-3, §5.9), and the schema-registry backend
  (no method added to `NatsKvSchemaRegistry`). The Phase-2 canonical
  verifier flow is now end-to-end composable from an `aip:web:`
  identifier through to `verify_entry_signature` — see §5.10
  composition pattern.
- **Phase-2 AIP-document signature-verification cache tier: CONSUMED
  in Sprint-4 Tag-5.** Module:
  `wirelang/identity/aip_signature_verification_cache.py`. Tests:
  `wirelang/tests/test_aip_signature_verification_cache.py`
  (T-AIP-SVC-01..12). Previously listed as a Phase-3 Identity-
  Substrate slot in §5.3; Sprint-4 Tag-5 ships it now to round out
  the Phase-2 verifier-pipeline performance profile. The cache is
  a bounded LRU+TTL tier (default `max_entries=256`,
  `ttl_seconds=300.0`, `clock=time.monotonic`) on top of the
  Sprint-4 Tag-1 `wirelang.identity.verify_aip_signature`
  primitive; cache hits are byte-equal to fresh verify outcomes.
  The cache key is SHA-256 over the 5-tuple
  `(SHA-256(JCS(body without document_signature)), alg, kid,
  signature_hex, pub_key_hex)` — byte-identical in shape to the
  Sprint-4 Tag-4 `jcs_sha256_hex` byte-anchor (Z-1-K-Sprint-4-2
  JCS-Resolver-Lock preserved). Negative outcomes (`verify`
  returns `False`) are memoised the same way as positive outcomes;
  structural failures (`ValueError` from the verifier) are NOT
  cached and propagate verbatim. The cache is byte-orthogonal to
  `wirelang.identity.verify_aip_signature` (UNCHANGED),
  `wirelang.identity.kid_resolver` (UNCHANGED),
  `wirelang.identity.aip_document_transport_fetch` (UNCHANGED), and
  the schema-registry backend (`NatsKvSchemaRegistry` UNCHANGED, no
  new method, no new envelope). See §5.11 composition pattern for
  the end-to-end Phase-2 cached-verifier flow.
- **Phase-2 `registered_by`-capability-gating: CONSUMED in Sprint-4
  Tag-6.** Module: `wirelang/schemas/registered_by_capability.py`.
  Tests: `wirelang/tests/test_registered_by_capability.py`
  (T-RBC-01..12; 45 sub-tests). Previously listed as a follow-up
  Phase-2 slot in §5.8 boundary block (Sprint-4 Tag-1 noted that
  capability-token gating on `registered_by` was reserved); Sprint-4
  Tag-6 ships the in-process policy-bundle + gating-function tier
  as a *prelude* to the full Biscuit-v3 binary-token machinery
  (the on-the-wire envelope schema at
  `wirelang/schemas/layer-3-capability-token.json` remains
  unchanged; full Biscuit encode/decode + Datalog evaluation is a
  Phase-3 slot). The gate is *additive* authorisation policy on
  top of the Sprint-4 Tag-1 `verify_entry_signature` cryptographic
  primitive; cryptographic correctness remains the single source
  of truth in `wirelang.schemas.entry_signing`. The gate is
  byte-orthogonal to `wirelang.schemas.entry_signing.sign_entry` /
  `verify_entry_signature` (UNCHANGED),
  `wirelang.identity.verify_aip_signature` (UNCHANGED),
  `wirelang.identity.kid_resolver` (UNCHANGED),
  `wirelang.identity.aip_document_transport_fetch` (UNCHANGED),
  `wirelang.identity.aip_signature_verification_cache` (UNCHANGED),
  and the schema-registry backend (`NatsKvSchemaRegistry`
  UNCHANGED, no new method, no new envelope, no new validation
  gate at write time). See §5.12 composition pattern for the
  end-to-end Phase-2 capability-gated publish flow.
- Phase-2 Biscuit binary token encode/decode + Datalog evaluation:
  reserved (Phase-3 slot; the Sprint-4 Tag-6 gate is the in-process
  policy-bundle prelude).
- ~~Phase-2 capability-policy distribution (persisted NATS-KV
  bucket `wakir-capability-policies` or analogous): reserved
  (Phase-3 slot; the Sprint-4 Tag-6 registry is in-process only).~~
  (**CONSUMED in Sprint-5 Tag-2** by
  `wirelang.schemas.capability_policy_nats_kv_backend`; see §5.14.
  The Sprint-5 Tag-2 module ships the persistent-distribution tier
  for capability policies on the `wakir-capability-policies` bucket;
  the Sprint-4 Tag-6 in-process `CapabilityPolicyRegistry` remains
  the gate-evaluation surface and is materialised from the bucket
  via `NatsKvCapabilityPolicyBackend.snapshot_registry`. CAS-pinned
  upserts (LWW-only in Sprint-5 Tag-2; Phase-3 slot) and watch-stream
  tail (full-snapshot only in Sprint-5 Tag-2; Phase-3 slot) remain
  follow-up slots. ~~Publisher-CLI `--capability-bucket` integration
  (Sprint-5 Tag-3+ candidate)~~ **CONSUMED in Sprint-5 Tag-3** via
  the `--capability-bucket` flag in `wirelang.schemas.publisher_cli`;
  the bucket-source gate decision is byte-equal to the file-source
  path with `gate_policy_source` as the only receipt audit difference;
  see §5.13's "Bucket policy source (Sprint-5 Tag-3)" subsection and
  §6.10's "Bucket policy source tests" addendum.)
- ~~Phase-2 publisher-CLI integration of the Sprint-4 Tag-6 gate:
  reserved (`wakir-schema-registry publish` flag that runs
  `gate_signed_entry` between `sign_entry` and `put`).~~
  **CONSUMED in Sprint-5 Tag-1** (`wirelang/schemas/publisher_cli.py`
  `--sign` / `--kid` / `--ed25519-priv-key-{hex,file}` / `--gate` /
  `--capability-registry` / `--gate-as-of` flags; new exit code
  `ExitCode.CAPABILITY_DENY = 7`; §5.13 ships the operator-CLI
  contract; §6.10 ships T-SR-PUB-CG-01..10). Sprint-5 Tag-1
  boundary leaves the on-the-wire envelope UNCHANGED (no signature
  on the bucket; that is a Sprint-5 Tag-2+ slot).
- **Phase-2 capability-policy CAS-pin: CONSUMED in Sprint-5 Tag-4.**
  Module: `wirelang/schemas/capability_policy_nats_kv_backend.py`
  (additive on the Sprint-5 Tag-2 module; the LWW path is byte-
  unchanged). Tests:
  `wirelang/tests/test_capability_policy_cas_pin.py`
  (T-CPP-CAS-01..10 + 2 aux). Closes the Sprint-5 Tag-2 §5.14
  boundary item "future CAS-pinned upsert path on the capability-
  policy bucket". The CAS-pin surface is a byte-precise
  pattern-mirror on the Phase-1b Sprint-3 Tag-3 schema-registry
  CAS-pin surface: identical typed-exception shape (
  `CapabilityPolicyConflictError` mirrors
  `SchemaRegistryConflictError`); identical helper functions
  (`_kv_update_with_revision`, `_is_conflict_exception`,
  `_extract_actual_revision`, `_coerce_revision_from_entry`,
  `_CONFLICT_CLS_MARKERS`) inlined into the capability-policy module
  rather than imported across modules (intentional decoupling so
  the two backends can evolve independently); identical validation-
  gate ordering (gates run BEFORE CAS); identical KV-adapter 3-shape
  contract (`update(last=)` / positional / `put(expected_revision=)`).
  The Sprint-5 Tag-2 LWW `put` path is byte-unchanged and remains
  the default for create-once / rarely-touched policy authorship
  flows. CAS-pin is the opt-in lost-update-protection surface for
  concurrent-authorship flows (e.g. `allowed_kids` rotation on a
  key-rollover). Cross-Review-Zone-1 non-touched; Cross-Review-
  Zone-B non-touched (the `wakir-capability-policies` bucket
  configuration is byte-unchanged — `history=5` already supports
  CAS-pin naturally). ~~The Phase-3 capability-policy watch-stream
  slot~~ (**CONSUMED in Sprint-5 Tag-5** — see §5.14 Watch-stream
  operational contract; ships `NatsKvCapabilityPolicyBackend.watch`,
  `CapabilityPolicyWatchEvent`, `CapabilityPolicyWatchOp`,
  `LiveCapabilityPolicySnapshot`, `open_capability_policy_watch_stream`)
  and the Phase-3 multi-replica CAS-quorum slot (still
  reserved) remain on the Phase-2/Phase-3 boundary; the Sprint-5
  Tag-5 watch-stream is the live-tail consumer substrate, not a
  CAS-quorum promotion. Sprint-5 Tag-5+ candidate: publisher-CLI
  composition of the live-tail consumer (a `--capability-bucket-watch`
  flag or daemon-mode subcommand) — explicitly NOT Tag-5.
- Phase-2 STRICT-mode activation toggle: reserved (Z-1-K-Sprint-4-4
  open; operator-controlled toggle is a Phase-2-roadmap consensus
  question).
- **Phase-2 capability-policy explicit revocation: CONSUMED in
  Sprint-6 Tag-1.** Modules:
  `wirelang/schemas/registered_by_capability.py` (additive: `CapabilityPolicy.revoked_at`,
  `CapabilityPolicy.revocation_reason`, `DecisionSource.POLICY_REVOKED`,
  `_is_revoked`; gate-precedence amendment) and
  `wirelang/schemas/capability_policy_nats_kv_backend.py` (additive:
  envelope keys `revoked_at` / `revocation_reason`, typed exception
  `CapabilityPolicyRevocationConflict`, `put_with_revision` Gate-3
  revocation-monotonicity check). Tests:
  `wirelang/tests/test_capability_policy_revocation.py`
  (T-CPP-REV-01..10 + 2 aux). Revocation is distinct from the
  Sprint-4 Tag-6 `disabled` soft kill-switch: `disabled` is a
  reversible operator-side state; `revoked_at` is an irreversible
  authority gesture monotonic at the CAS-pin write path. The
  Sprint-6 Tag-1 surface is *policy-level* revocation; *token-level*
  revocation (binary-token revocation-list interpretation) lives in
  the Phase-3 Datalog substrate per
  `wirelang/schemas/layer-3-capability-token.json` and remains a
  Phase-3 slot. Sprint-6 Tag-1+ candidates: publisher-CLI `--revoke`
  flag composing the CAS-pin revocation path (CONSUMED in Sprint-6
  Tag-2, v0.17.0); watch-stream consumer-side revocation-event
  filter helper (CONSUMED in Sprint-6 Tag-3, v0.18.0); cross-bucket
  revocation replication (CONSUMED in Sprint-6 Tag-6, v0.19.0 — see
  `wirelang/schemas/capability_policy_replication.py`; the new
  layer carries the revocation-monotonic invariant byte-precisely
  across the cross-bucket boundary, with the in-band
  `_is_revocation_breach` check on the SOURCE_WINS path and the
  server-side `CapabilityPolicyRevocationConflict` catch on the
  CAS_PIN path). Cross-Review-Zone-1 non-touched
  (the four Z-1-K-Sprint-4 consensus points remain byte-identical;
  revocation is policy-layer authority, not a cryptographic
  primitive). Cross-Review-Zone-B non-touched (the
  `wakir-capability-policies` bucket configuration is byte-unchanged
  — `history=5` retains the pre-revocation envelope for audit).

## 8. Compatibility statement

The Phase-1b registry is purely additive relative to Phase-1a /
Phase-1b Sprint-2: no on-disk loader is removed, no verifier module
is forced to switch to the registry. Verifiers that already load
schemas via `importlib.resources` continue to function unchanged.
The registry is a **production-target substrate** that Phase-2
deployment will switch to; Phase-1b Sprint-3 Tag-1 lands the
substrate, Tag-3 hardens it with the CAS-pin path. The cutover
itself is still Phase-2.

**Tag-3 (v0.2.0) is additive relative to Tag-1 (v0.1.0):**

- All Tag-1 surfaces (`get` / `put` / `delete` / `list_keys` /
  `snapshot` / `get_by_triple`) remain unchanged. Their
  contracts are preserved byte-equal.
- The Tag-3 additions (`get_with_revision` / `put_with_revision` /
  `SchemaRegistryConflictError`) are NEW surfaces. Callers that do
  not need lost-update protection continue to use `put` (LWW); they
  are not forced onto the CAS-pin path.
- M-2 conformance (additive-only schema evolution): Tag-3 adds no
  new envelope fields and modifies no existing field. The on-the-wire
  envelope schema remains `wakir.wirelang.schema-registry-entry/1`.
- M-4 conformance (multi-version-aware registry): Tag-3 is orthogonal
  to the version axis; CAS-pin operates on a single key
  (`schemas/<layer>/<name>/<version>`) and does not depend on whether
  multiple versions are simultaneously active.
- Spec semver bump 0.1.0 → 0.2.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

**Tag-4 (v0.3.0) is additive relative to Tag-3 (v0.2.0):**

- All Tag-1 + Tag-3 surfaces remain unchanged. Tag-4 introduces
  no breaking change to `get` / `put` / `delete` / `list_keys` /
  `snapshot` / `get_by_triple` / `get_with_revision` /
  `put_with_revision`. Their contracts are preserved byte-equal.
- The Tag-4 additions (`watch` / `WatchOp` / `WatchEvent` /
  `LiveSchemaSnapshot` / `open_watch_stream`) are NEW surfaces.
  Callers that do not need an incremental view continue to take
  full snapshots; they are not forced onto the watch-stream path.
- M-2 conformance (additive-only schema evolution): Tag-4 adds no
  new envelope fields and modifies no existing field. The on-the-wire
  envelope schema remains `wakir.wirelang.schema-registry-entry/1`.
  Watch events carry the same envelope bytes as a full-snapshot
  read; the decoder is shared (`_envelope_to_entry`).
- M-4 conformance (multi-version-aware registry): Tag-4 is orthogonal
  to the version axis; the watch-stream surfaces `WatchEvent` per
  bucket key (`schemas/<layer>/<name>/<version>`) and does not depend
  on whether multiple versions are simultaneously active. A
  `LiveSchemaSnapshot` materialises the same multi-version-aware
  `InMemorySchemaRegistry` as the full-snapshot path.
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. Verifier
  modules that already consume frozen `InMemorySchemaRegistry`
  views continue to function unchanged when the producer is a
  `LiveSchemaSnapshot.as_registry()` instead of `backend.snapshot()`.
- Spec semver bump 0.2.0 → 0.3.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

**Tag-5 (v0.4.0) is additive relative to Tag-4 (v0.3.0):**

- All Tag-1 + Tag-3 + Tag-4 surfaces remain unchanged. Tag-5
  introduces no new method on `NatsKvSchemaRegistry`, no new field
  on `SchemaRegistryEntry`, and no new on-the-wire envelope.
- The Tag-5 addition is a *separate module*
  (`wirelang.schemas.publisher_cli`) consisting of an argparse
  surface, an `ExitCode` enum, a `PublishReceipt` dataclass, and a
  `run()` entry-point. Existing callers that consume the backend
  directly (verifier modules, watch-stream consumers) are untouched.
- M-2 conformance (additive-only schema evolution): Tag-5 adds no
  new envelope fields and modifies no existing field. The on-the-wire
  envelope schema remains `wakir.wirelang.schema-registry-entry/1`.
  The CLI is a routing layer onto the existing backend gates; it
  does not introduce an alternative codec.
- M-4 conformance (multi-version-aware registry): Tag-5 is orthogonal
  to the version axis. The CLI publishes one `(layer, name, version)`
  entry per invocation; multi-version coexistence on the bucket is
  unaffected.
- Spec semver bump 0.3.0 → 0.4.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

**Tag-6 (v0.5.0) is additive relative to Tag-5 (v0.4.0):**

- All Tag-1 + Tag-3 + Tag-4 + Tag-5 surfaces remain unchanged.
  Tag-6 introduces no new method on `NatsKvSchemaRegistry`, no new
  field on `SchemaRegistryEntry`, and no new on-the-wire envelope.
- The Tag-6 addition is a *separate module*
  (`wirelang.schemas.replication`) consisting of `SchemaReplicator`,
  `bootstrap_target_from_source`, `ReplicationConflictPolicy`,
  `ReplicationDecision`, `ReplicationFilter`, and
  `ReplicationMetrics`. The replication module is a *consumer* of
  Tag-1 LWW + Tag-3 CAS-pin + Tag-4 watch-stream surfaces; it
  imports them but does not modify them.
- Existing callers that consume the backend directly (verifier
  modules, watch-stream consumers, the publisher CLI) are untouched.
- M-2 conformance (additive-only schema evolution): Tag-6 adds no
  new envelope fields and modifies no existing field. The on-the-wire
  envelope schema remains `wakir.wirelang.schema-registry-entry/1`.
  The replicator transports the same envelope bytes across buckets;
  the encoder / decoder is shared (`_entry_to_envelope` /
  `_envelope_to_entry` from the Tag-1 backend).
- M-4 conformance (multi-version-aware registry): Tag-6 is orthogonal
  to the version axis. The replicator mirrors entries per bucket key
  (`schemas/<layer>/<name>/<version>`) without depending on whether
  multiple versions are simultaneously active on either bucket.
- Spec semver bump 0.4.0 → 0.5.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

**Phase-2 Sprint-4 Tag-1 (v0.6.0) is additive relative to Tag-6 (v0.5.0):**

- All Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 surfaces remain
  unchanged. Sprint-4 Tag-1 introduces no new method on
  `NatsKvSchemaRegistry`.
- The Sprint-4 Tag-1 addition is a *separate module*
  (`wirelang.schemas.entry_signing`) consisting of
  `SignedSchemaRegistryEntry`, `sign_entry`,
  `verify_entry_signature`, `envelope_with_signature`,
  `envelope_to_signed_entry`, `SchemaRegistrySignatureError`, and
  `VerifyMode`. The signing module is a *consumer* of the Tag-1
  envelope codec (`_entry_to_envelope` / `_envelope_to_entry`)
  and of `wirelang.identity.aip_signing`'s JCS+SHA-256+Ed25519
  primitive; it imports them but does not modify them.
- The Tag-1 envelope codec (`_entry_to_envelope` /
  `_envelope_to_entry`) is left UNCHANGED in Sprint-4 Tag-1. The
  new `envelope_with_signature` / `envelope_to_signed_entry`
  helpers in `wirelang.schemas.entry_signing` provide the
  envelope-with-signature round-trip. Unsigned envelopes emitted by
  the Tag-1 codec remain byte-equal to v0.5.0 output (backward
  compatibility invariant); signed envelopes emitted by
  `envelope_with_signature` differ from the Tag-1 output by exactly
  the one optional `signature` slot.
- M-2 conformance (additive-only schema evolution): Sprint-4 Tag-1
  adds ONE optional field (`signature`) to the existing
  `wakir.wirelang.schema-registry-entry/1` envelope; no field is
  modified or removed. v0.5.0 readers tolerate the new optional
  field. The on-the-wire envelope schema URI is unchanged (no `/2`
  envelope is introduced).
- M-4 conformance (multi-version-aware registry): Sprint-4 Tag-1
  is orthogonal to the version axis. Signing operates on one entry
  envelope (`schemas/<layer>/<name>/<version>`) and is independent
  of whether multiple versions are simultaneously active.
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. Verifier
  modules that consume frozen `InMemorySchemaRegistry` views are
  not forced onto the signing path; signing is opt-in at the
  envelope-build boundary.
- Spec semver bump 0.5.0 → 0.6.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive).

**Phase-2 Sprint-4 Tag-3 (v0.7.0) is additive relative to Sprint-4 Tag-1 (v0.6.0):**

- All Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 + Sprint-4 Tag-1 surfaces
  remain unchanged. Sprint-4 Tag-3 introduces no new method on
  `NatsKvSchemaRegistry` and no modification to
  `wirelang.schemas.entry_signing`.
- The Sprint-4 Tag-3 addition is a *separate module*
  (`wirelang.identity.kid_resolver`) consisting of the pure
  functions `resolve_kid` / `list_resolvable_kids`, the frozen
  dataclass `ResolvedPublicKey`, and the typed exception
  `KidResolverError`. The resolver is exposed via the
  `wirelang.identity` package `__init__`.
- The on-the-wire envelope schema is UNCHANGED. The resolver reads
  from AIP documents (`wirelang/schemas/aip-document.json`); it
  does not emit, write, or canonicalise envelope bytes.
- The `wirelang.schemas.entry_signing` module is UNCHANGED. The
  resolver is a *peer* layer — callers compose the two: read AIP
  doc → `resolve_kid` → `verify_entry_signature`. The signing
  module does NOT import the resolver; this preserves the Sprint-4
  Tag-1 design that the signing module treats the public key as
  caller-supplied.
- M-2 conformance (additive-only schema evolution): Sprint-4 Tag-3
  adds NO new envelope field. The schema-registry on-the-wire
  surface (envelope shape, value-schema URI
  `wakir.wirelang.schema-registry-entry/1`, signature-block shape)
  is bit-equal to v0.6.0. M-2 is preserved trivially.
- M-4 conformance (multi-version-aware registry): Sprint-4 Tag-3
  is orthogonal to the version axis. The resolver operates on
  AIP documents (one per agent identity), not on registry entries.
- The AIP-document JSON-Schema
  (`wirelang/schemas/aip-document.json`) is UNCHANGED. The resolver
  reads existing fields (`kid`, `alg`, `key_hex`, `validafter`,
  `validuntil`, `purpose`); no new field is introduced and no
  field semantics is altered.
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. The kid-
  resolver is opt-in: verifiers that do not consume signatures are
  not forced onto the resolver path.
- Spec semver bump 0.6.0 → 0.7.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive). The bump is
  warranted by the new §5.9 operational contract and §6.6 test
  inventory; no breaking-change to any consumer.

**Phase-2 Sprint-4 Tag-4 (v0.8.0) is additive relative to Sprint-4 Tag-3 (v0.7.0):**

- All Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 + Sprint-4 Tag-1 +
  Sprint-4 Tag-3 surfaces remain unchanged. Sprint-4 Tag-4 introduces
  no new method on `NatsKvSchemaRegistry`, no modification to
  `wirelang.schemas.entry_signing`, and no modification to
  `wirelang.identity.kid_resolver` (the Sprint-4 Tag-3 surface).
- The Sprint-4 Tag-4 addition is a *separate module*
  (`wirelang.identity.aip_document_transport_fetch`) consisting of
  the pure function `fetch_aip_document`, the URL-mapping helper
  `aip_web_to_https_url`, the frozen dataclass `AipFetchResult`, the
  typed exception tree `AipDocumentTransportError` →
  {`AipUrlSchemeError`, `AipDnsAnchorMismatchError`}, and the
  module-level constants `WELL_KNOWN_AIP_PREFIX` /
  `DNS_ANCHOR_PREFIX`. The fetcher is exposed via the
  `wirelang.identity` package `__init__`.
- The on-the-wire envelope schema is UNCHANGED. The fetcher reads
  AIP documents from HTTPS; it does not emit, write, or canonicalise
  schema-registry envelope bytes.
- `wirelang.schemas.entry_signing` is UNCHANGED. `wirelang.identity.kid_resolver`
  is UNCHANGED. `wirelang.identity.aip_signing` is UNCHANGED. The
  fetcher consumes `wirelang.identity.aip_signing._jcs_canonicalize`
  via a lazy import (the canonicaliser is shared byte-identical with
  the signing path; no new JCS path introduced).
- The V-908 HTTPS-transport surface (`HTTPSDocumentTransport` and
  its exception tree `HTTPSBackendError` + subclasses) is UNCHANGED.
  The fetcher composes the existing transport without wrapping or
  re-parsing.
- The V-908 DNS-anchor surface (`dns_anchor.TxtResolver`,
  `dns_anchor.fetch_anchor`, `dns_anchor.parse_anchor`,
  `DnsAnchor`, `DnsAnchorError`) is UNCHANGED. The Wakir-AIP TXT-
  record prefix (`_wakir-aip.`) is a parallel slot to the Wakir-FTD
  prefix (`_wakir-ftd.`); the on-wire format is byte-identical
  (`v=1; sha256=<64-hex>`); the parser is reused verbatim.
- M-2 conformance (additive-only schema evolution): Sprint-4 Tag-4
  adds NO new envelope field. The schema-registry on-the-wire surface
  (envelope shape, value-schema URI
  `wakir.wirelang.schema-registry-entry/1`, signature-block shape)
  is bit-equal to v0.7.0. M-2 is preserved trivially.
- M-4 conformance (multi-version-aware registry): Sprint-4 Tag-4
  is orthogonal to the version axis. The fetcher operates on AIP
  documents (one per agent identity), not on registry entries.
- The AIP-document JSON-Schema (`wirelang/schemas/aip-document.json`)
  is UNCHANGED. The fetcher reads the body opaquely and does not
  validate it against the schema (schema-validation belongs to
  Phase-1a `aip_resolver`).
- Cross-Review-Zone-1 (Identity-Substrate) non-touched: the four
  Z-1-K-Sprint-4 consensus points remain byte-identical. The Tag-4
  `anchor_required` toggle is an *orthogonal* hard-vs-soft policy
  governing the transport-trust step; it is semantically distinct
  from the Sprint-4 Tag-1 `VerifyMode.STRICT` signature-policy toggle
  (Z-1-K-Sprint-4-4).
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. The transport-
  fetch layer is opt-in: verifiers that consume out-of-band AIP
  documents (e.g. from a sidecar cache) are not forced onto the
  fetcher path.
- Spec semver bump 0.7.0 → 0.8.0 reflects the additive minor change
  (M-2 §3.2 versioning policy: minor for additive). The bump is
  warranted by the new §5.10 operational contract and §6.7 test
  inventory; no breaking-change to any consumer.

**Phase-2 Sprint-4 Tag-5 (v0.9.0) is additive relative to Sprint-4 Tag-4 (v0.8.0):**

- All Tag-1 + Tag-3 + Tag-4 + Tag-5 + Tag-6 + Sprint-4 Tag-1 +
  Sprint-4 Tag-3 + Sprint-4 Tag-4 surfaces remain unchanged.
  Sprint-4 Tag-5 introduces no new method on
  `NatsKvSchemaRegistry`, no modification to
  `wirelang.schemas.entry_signing`, no modification to
  `wirelang.identity.kid_resolver` (Sprint-4 Tag-3),
  no modification to `wirelang.identity.aip_document_transport_fetch`
  (Sprint-4 Tag-4), and no modification to
  `wirelang.identity.aip_signing` (the underlying
  `verify_aip_signature` primitive is the cache miss-path target
  and remains the single source of truth for cryptographic
  correctness).
- The Sprint-4 Tag-5 addition is a *separate module*
  (`wirelang.identity.aip_signature_verification_cache`) consisting
  of the bounded LRU+TTL class `AipSignatureVerificationCache`,
  the frozen counter dataclass `CacheStats`, the free function
  `cached_verify_aip_signature`, and the module-level constants
  `DEFAULT_MAX_ENTRIES=256` / `DEFAULT_TTL_SECONDS=300.0`. The
  cache is exposed via the `wirelang.identity` package `__init__`.
- The on-the-wire envelope schema is UNCHANGED. The cache memoises
  the Boolean outcome of a verify call; it does not emit, write,
  or canonicalise schema-registry envelope bytes.
- `wirelang.schemas.entry_signing` is UNCHANGED.
  `wirelang.identity.kid_resolver` is UNCHANGED.
  `wirelang.identity.aip_document_transport_fetch` is UNCHANGED.
  `wirelang.identity.aip_signing` is UNCHANGED. The cache consumes
  `wirelang.identity.aip_signing._jcs_canonicalize` byte-identical
  for the body-digest computation (the Z-1-K-Sprint-4-2 JCS-
  Resolver-Lock is preserved; no new JCS path introduced).
- The cache's body-digest helper (`_jcs_body_digest_hex`) is
  byte-equal in shape and output to the Sprint-4 Tag-4
  `aip_document_transport_fetch._jcs_anchor_hex` helper. The two
  helpers are deliberate siblings (parallel modules, not a stack);
  the byte-equality is by construction (same JCS canonicaliser,
  same SHA-256, same `document_signature`-strip).
- M-2 conformance (additive-only schema evolution): Sprint-4 Tag-5
  adds NO new envelope field. The schema-registry on-the-wire
  surface (envelope shape, value-schema URI
  `wakir.wirelang.schema-registry-entry/1`, signature-block shape)
  is bit-equal to v0.8.0. M-2 is preserved trivially.
- M-4 conformance (multi-version-aware registry): Sprint-4 Tag-5
  is orthogonal to the version axis. The cache operates on AIP-
  document verify outcomes, not on registry entries.
- The AIP-document JSON-Schema (`wirelang/schemas/aip-document.json`)
  is UNCHANGED. The cache reads the body opaquely and does not
  validate it against the schema.
- Cross-Review-Zone-1 (Identity-Substrate) non-touched: the four
  Z-1-K-Sprint-4 consensus points remain byte-identical. The cache
  is curve-agnostic (Z-1-K-Sprint-4-3 non-touched / reinforced),
  policy-agnostic (Z-1-K-Sprint-4-4 non-touched), and
  resolver-independent (Z-1-K-Sprint-4-1 non-touched — the cache
  takes a `pub_key` argument the caller has already resolved).
  Z-1-K-Sprint-4-2 (JCS-Resolver-Lock) is preserved byte-identical
  via the direct `aip_signing._jcs_canonicalize` reuse.
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. The cache
  tier is opt-in: verifiers that re-validate the same triple at
  fleet scale benefit from the cache; verifiers that validate each
  triple once can call `verify_aip_signature` directly without
  going through the cache surface.
- Spec semver bump 0.8.0 → 0.9.0 reflects the additive minor
  change (M-2 §3.2 versioning policy: minor for additive). The
  bump is warranted by the new §5.11 operational contract and
  §6.8 test inventory; no breaking-change to any consumer.

**Phase-2 Sprint-4 Tag-6 (v0.10.0) is additive relative to Sprint-4 Tag-5 (v0.9.0):**

- All Sprint-4 Tag-1 + Tag-3 + Tag-4 + Tag-5 surfaces remain
  unchanged. Tag-6 introduces no breaking change to
  `wirelang.schemas.entry_signing` (`SignedSchemaRegistryEntry` /
  `sign_entry` / `verify_entry_signature` /
  `envelope_with_signature` / `envelope_to_signed_entry` /
  `SchemaRegistrySignatureError` / `VerifyMode` UNCHANGED), to
  `wirelang.identity.aip_signing`
  (`sign_aip_document` / `verify_aip_signature` UNCHANGED), to
  `wirelang.identity.kid_resolver` (`resolve_kid` /
  `list_resolvable_kids` / `ResolvedPublicKey` / `KidResolverError`
  UNCHANGED), to
  `wirelang.identity.aip_document_transport_fetch`
  (`fetch_aip_document` / `aip_web_to_https_url` / `AipFetchResult` /
  error tree UNCHANGED), to
  `wirelang.identity.aip_signature_verification_cache`
  (`AipSignatureVerificationCache` / `CacheStats` /
  `cached_verify_aip_signature` UNCHANGED), or to any
  `NatsKvSchemaRegistry` surface. Their contracts are preserved
  byte-equal.
- The Tag-6 additions (`CapabilityPolicy` /
  `CapabilityPolicyRegistry` / `CapabilityGateDecision` /
  `DecisionSource` / `check_registered_by_capability` /
  `gate_signed_entry` / `RegisteredByCapabilityError` plus the
  module-level `__all__` listing) are NEW surfaces in a NEW
  module (`wirelang/schemas/registered_by_capability.py`).
  Callers that do not need capability-gating continue to use the
  Tag-1 entry-signing layer directly; they are not forced onto
  the gate.
- M-2 conformance (additive-only schema evolution): Tag-6 adds no
  new envelope fields and modifies no existing field. The
  on-the-wire envelope schema remains
  `wakir.wirelang.schema-registry-entry/1`. The on-the-wire
  Biscuit-v3 capability-token JSON envelope schema
  (`wirelang/schemas/layer-3-capability-token.json`) is
  REFERENCED only (as the target shape for Phase-3
  substantiation); the Tag-6 in-process policy bundle uses a
  separate Python dataclass that does NOT yet round-trip through
  that JSON envelope. The two surfaces are intentionally
  separate at Tag-6: the in-process bundle ships now; the
  on-the-wire serialisation is Phase-3.
- M-4 conformance (multi-version-aware registry): Tag-6 is
  orthogonal to the version axis; capability-gating operates on
  the `(registered_by, kid, layer, name)` 4-tuple and does not
  depend on whether multiple versions of the same triple are
  simultaneously active.
- Cross-Review-Zone-1 (Identity-Substrate) **non-touched**: the
  four Z-1-K-Sprint-4 consensus points remain byte-identical
  after Tag-6. The gate is curve-agnostic (Z-1-K-Sprint-4-3
  reinforced — Ed25519 is the entry-signing curve, but the gate
  carries no curve choice of its own); JCS-free (Z-1-K-Sprint-4-2
  preserved — no canonicalisation in the gating module);
  resolver-independent (Z-1-K-Sprint-4-1 non-touched — the gate
  consumes the kid byte-equal as the caller supplied it, does not
  call `kid_resolver`); and orthogonal to `VerifyMode`
  (Z-1-K-Sprint-4-4 non-touched — the gate is *additional*
  authorisation policy, not a swap for the cryptographic-
  verification mode toggle).
- The synchronous verifier surface (`InMemorySchemaRegistry.lookup`
  / `lookup_by_triple` / `keys_sorted`) is unchanged. The gate is
  opt-in: callers that want capability-gating wire
  `check_registered_by_capability` or `gate_signed_entry` into
  their publish flow between cryptographic verification and the
  backend write; callers that do not are not forced onto the gate.
- Spec semver bump 0.9.0 → 0.10.0 reflects the additive minor
  change (M-2 §3.2 versioning policy: minor for additive). The
  bump is warranted by the new §5.12 operational contract and
  §6.9 test inventory; no breaking-change to any consumer.

**Sprint-5 Tag-1 (v0.11.0) is additive relative to Sprint-4 Tag-6 (v0.10.0):**

- All Sprint-3 Tag-1 / Tag-3 / Tag-4 / Tag-5 / Tag-6 surfaces and
  all Sprint-4 Tag-1 / Tag-3 / Tag-4 / Tag-5 / Tag-6 surfaces remain
  unchanged. Their contracts are preserved byte-equal.
- The Sprint-5 Tag-1 additions are *operator-CLI* surface extensions
  on `wirelang/schemas/publisher_cli.py` only: seven new flags
  (`--sign`, `--kid`, `--ed25519-priv-key-hex`,
  `--ed25519-priv-key-file`, `--gate`, `--capability-registry`,
  `--gate-as-of`), one new exit code
  (`ExitCode.CAPABILITY_DENY = 7`), three additive optional fields
  on `PublishReceipt` (`signed`, `kid`, `gate_decision`), and six
  internal helpers (`_validate_capability_flag_consistency`,
  `_load_ed25519_priv_key`, `_decode_hex_seed`,
  `_load_capability_registry`, `_policy_from_dict`,
  `_parse_optional_rfc3339`, `_decision_to_dict`). Pre-Sprint-5
  invocations (no capability flags) emit a receipt with
  `signed=false`, `kid=null`, `gate_decision=null` and exit codes
  in the byte-equal pre-Sprint-5 matrix; no caller is forced onto
  the capability path.
- M-2 conformance (additive-only schema evolution): Sprint-5 Tag-1
  adds no new on-the-wire envelope fields and modifies no existing
  field. The schema-registry envelope schema remains
  `wakir.wirelang.schema-registry-entry/1`. The capability-registry
  JSON file is an *operator-side* file format only; it is NOT
  written to the `wakir-schemas` bucket. The Biscuit-v3 capability
  token JSON envelope (`wirelang/schemas/layer-3-capability-token.json`)
  is REFERENCED only; the Sprint-5 Tag-1 file format is a separate,
  simpler operator-side surface intended for Phase-3 promotion to
  the Biscuit envelope.
- M-4 conformance (multi-version-aware registry): Sprint-5 Tag-1 is
  orthogonal to the version axis; the gate operates on the
  `(registered_by, kid, layer, name)` 4-tuple per Tag-6 contract and
  is unaffected by multiple versions of the same triple being
  simultaneously active.
- Receipt-shape additivity: the three new optional receipt fields
  are at the end of the `PublishReceipt` dataclass and the
  serialised JSON object's key set. Consumers that index by the
  pre-Sprint-5 field set continue to read byte-equal pre-existing
  fields; consumers that index by the new fields receive an
  unambiguous "feature-off" marker. The JSON serialisation uses
  `sort_keys=True` so the new fields are sorted into the canonical
  position; consumers that compare full canonical JSON serialisations
  byte-for-byte across Sprint-4 Tag-6 and Sprint-5 Tag-1 receipts
  WILL see a difference (the three new keys), but consumers that
  filter to the pre-Sprint-5 key set will not. The minor-version
  bump reflects this.
- Cross-Review-Zone-1 (Identity-Substrate) **non-touched**: the four
  Z-1-K-Sprint-4 consensus points remain byte-identical after
  Sprint-5 Tag-1. The integration is curve-agnostic at the
  CLI-flag layer (operator supplies the seed; the underlying
  `sign_entry` call is byte-identical to Tag-1); JCS-free at the
  CLI layer (canonicalisation lives inside `sign_entry`);
  resolver-independent (the operator supplies `--kid` directly;
  the CLI does NOT call `kid_resolver`); orthogonal to `VerifyMode`
  (the publisher path does NOT call `verify_entry_signature`).
- `entry_signing.sign_entry`, `entry_signing.verify_entry_signature`,
  `registered_by_capability.gate_signed_entry`, and
  `registered_by_capability.check_registered_by_capability` are
  imported and called byte-equal; none is modified. The
  `NatsKvSchemaRegistry.put` / `put_with_revision` write paths are
  byte-unchanged; the signed entry's underlying
  `SchemaRegistryEntry` is what reaches the backend, identical to
  the pre-Sprint-5 unsigned path. The signature block is consumed
  CLI-side only.
- The capability-deny short-circuit runs **before** the backend
  connect (`connect_factory` is not even called on a deny). The
  bucket is byte-untouched on a deny; the test inventory
  (T-SR-PUB-CG-04..06) pins this explicitly.
- Spec semver bump 0.10.0 → 0.11.0 reflects the additive minor
  change (M-2 §3.2 versioning policy: minor for additive). The
  bump is warranted by the new §5.13 operational contract and
  §6.10 test inventory; no breaking-change to any consumer.

**Sprint-5 Tag-2 (v0.12.0) is additive relative to Sprint-5 Tag-1 (v0.11.0):**

- A new module `wirelang.schemas.capability_policy_nats_kv_backend`
  is introduced. The Sprint-5 Tag-1 module
  `wirelang.schemas.publisher_cli` is byte-unchanged; the Sprint-4
  Tag-6 module `wirelang.schemas.registered_by_capability` is
  byte-unchanged; the Sprint-4 Tag-1 module
  `wirelang.schemas.entry_signing` is byte-unchanged; the Sprint-3
  Tag-1 / Tag-3 / Tag-4 / Tag-5 / Tag-6 modules
  (`registry_nats_kv_backend.py`, `publisher_cli.py`,
  `replication.py`) are byte-unchanged.
- A new dedicated NATS-KV bucket `wakir-capability-policies` is
  introduced on the operator-side cluster substrate. The existing
  six Phase-1 / Phase-2 buckets (`wakir-schemas`,
  `wakir-aip-cache`, `wakir-ftd-cache`, `wakir-ftd-poisoned`,
  `wakir-schema-registry-entries`, `wakir-federation-routes`) are
  byte-unchanged. The new bucket is the 7th slot on Kai's
  `PHASE_1_BUCKETS` inventory pending the Z-B paired-update
  (Sprint-5 Tag-3+ Kai-side slot).
- A new on-the-wire envelope schema URI
  `wakir.wirelang.capability-policy-entry/1` is introduced on the
  new bucket. The existing schema-registry envelope
  (`wakir.wirelang.schema-registry-entry/1`) on `wakir-schemas`
  remains byte-unchanged; no breaking-change to any pre-existing
  envelope; no change to any pre-existing bucket.
- M-2 conformance preserved: the new envelope is on a new bucket;
  no existing envelope field, type, or shape is altered.
  M-4 conformance preserved: the new module is on the same
  semver axis as the spec; orthogonal to envelope-schema versioning
  (the envelope is itself at `/1`, this is a new envelope-schema
  axis distinct from `schema-registry-entry/1`).
- Cross-Review-Zone-1 non-touched: the four Z-1-K-Sprint-4
  consensus points are byte-identical (the persistence layer is
  curve-agnostic at the `allowed_kids` axis, JCS-free at the
  policy-envelope axis — no on-the-wire digest of the policy
  envelope analogous to `schema_body_sha256`; kid-resolver-
  independent — the resolver runs upstream of the gate;
  orthogonal to `VerifyMode` — the persistence layer ships
  persistence, not verification).
- Cross-Review-Zone-B **TRIGGERED**: the orchestrator-side
  `PHASE_1_BUCKETS` inventory gains a 7th slot. The Wirelang-side
  `BUCKET_CONFIG` constant is the byte-anchor; the orchestrator-
  side `BucketSpec` will mirror it byte-precisely on Kai-side
  acceptance. The paired-update memo
  (`agents-workspaces/kai/inbox/2026-05-11-reza-z-b-seventh-bucket-capability-policies-paired-update.md`)
  lists the byte-precise mirror contract. The Wirelang-side
  consumer is byte-functional once the bucket is materialised on
  the live cluster.
- The Sprint-4 Tag-6 in-process `CapabilityPolicyRegistry` remains
  the canonical evaluation surface. Sprint-5 Tag-2 ships the
  source-of-truth substrate that materialises it via
  `NatsKvCapabilityPolicyBackend.snapshot_registry`. The Sprint-4
  Tag-6 `check_registered_by_capability` function is byte-unchanged
  and consumes a `CapabilityPolicyRegistry` byte-identical whether
  the registry was assembled in-process from operator-supplied
  JSON (Sprint-5 Tag-1 path) or materialised from the persistent
  bucket (Sprint-5 Tag-2 path).
- The Sprint-5 Tag-1 publisher-CLI `--capability-registry` flag is
  byte-unchanged: it still reads operator-local JSON. A future
  `--capability-bucket` flag that reads policies from the
  Sprint-5 Tag-2 bucket is a Sprint-5 Tag-3+ candidate; Sprint-5
  Tag-2 is the substrate, not the CLI integration.
- The Sprint-5 Tag-2 backend ships PUT (LWW) only. A CAS-pin tier
  (`put_with_revision`) is reserved as a Phase-3 slot mirroring
  the Sprint-3 Tag-3 schema-registry CAS-pin pattern.
- The Sprint-5 Tag-2 backend ships full-snapshot only. A
  watch-stream tail (`watch()` / `WatchEvent` /
  `LiveCapabilityPolicySnapshot`) is reserved as a Phase-3 slot
  mirroring the Sprint-3 Tag-4 schema-registry watch-stream
  pattern.
- Spec semver bump 0.11.0 → 0.12.0 reflects the additive minor
  change (M-2 §3.2 versioning policy: minor for additive). The
  bump is warranted by the new §5.14 operational contract and
  §6.11 test inventory; no breaking-change to any consumer.

**Sprint-5 Tag-3 (v0.13.0) is additive relative to Sprint-5 Tag-2 (v0.12.0):**

- The `wirelang.schemas.publisher_cli` module gains the
  `--capability-bucket` flag and the
  `--capability-bucket-connect-url` flag in
  `_add_capability_flags`. The new policy-source axis is enforced
  at argparse level by an
  `add_mutually_exclusive_group` containing
  `--capability-registry` and `--capability-bucket`; supplying both
  raises `SystemExit(2)`. The
  `_validate_capability_flag_consistency` invariants are extended
  so `--gate` requires exactly one of the two sources and an
  orphan `--capability-bucket` (without `--gate`) is rejected with
  `INPUT_ERROR (exit 3)`.
- The `PublishReceipt` dataclass gains a fourth optional field
  `gate_policy_source: Optional[str]` (default `None`). Pre-Sprint-5
  receipts now carry the field at its default-off value; consumers
  that index by the legacy field set continue to read byte-equal
  pre-existing fields. Sort-keys JSON serialisation places the new
  field after `gate_decision` and before `kid` in the sorted output
  (because `g` < `k`); callers performing whole-document byte-compare
  across tag versions see the additive key. Per-key consumers see
  byte-equal values for the prior fields.
- The receipt's `gate_policy_source` is `"file"` for the Sprint-5
  Tag-1 file path, `"bucket"` for the new Sprint-5 Tag-3 bucket
  path, and `None` for any bare publish (no `--gate`). The gate
  decision itself is byte-equal regardless of source (verified by
  T-SR-PUB-CB-10 cross-source byte-equality).
- A new optional `capability_bucket_factory` kwarg on
  `publisher_cli.run()` carries the dependency-injection point for
  tests; the default factory
  `_default_capability_bucket_factory` connects to NATS-JetStream
  and opens `js.key_value("wakir-capability-policies")` via lazy
  import (the CLI module continues to load cleanly in environments
  without nats-py).
- The synchronous `_run_dry_run` is replaced by a thin
  `asyncio.run` wrapper over a new `_run_dry_run_async`. The change
  is invisible to operators (the CLI entry-point is unchanged) and
  to callers passing only the publish path. Hermetic test
  invocations of `dry-run` with `--capability-bucket` work
  byte-equal to the publish path through the same factory shape.
- The Sprint-5 Tag-2 `NatsKvCapabilityPolicyBackend` surface is
  byte-unchanged. Sprint-5 Tag-3 consumes
  `snapshot_registry()` exactly once per CLI invocation; no `put`,
  `delete`, or `watch` is invoked from the CLI path.
- The Sprint-5 Tag-2 bucket `wakir-capability-policies` is consumed
  as-is. No new bucket is requested; Cross-Review-Zone-B is
  non-touched at the Sprint-5 Tag-3 axis (the Sprint-5 Tag-2
  paired-update memo remains the canonical Z-B trigger).
- The schema-registry bucket (`wakir-schemas`) write path is
  byte-unchanged. A `CAPABILITY_DENY` on the bucket-source path
  short-circuits before the schema-bucket connect, identical to
  the Sprint-5 Tag-1 file-source short-circuit (verified by
  T-SR-PUB-CB-03..05).
- A poisoned bucket envelope (non-JSON value, schema-URI mismatch,
  malformed `allowed_triples`) raises
  `CapabilityPolicyBackendError` which the CLI routes through
  `ExitCode.VALIDATION_ERROR = 4` (T-SR-PUB-CB-08). The schema
  bucket remains untouched in that case.
- Spec semver bump 0.12.0 → 0.13.0 reflects the additive minor
  change (M-2 §3.2 versioning policy: minor for additive). The
  bump is warranted by the new §5.13 bucket-source subsection, the
  §6.10 bucket-source test addendum, and the new receipt field
  `gate_policy_source`; no breaking-change to any consumer.

**Sprint-5 Tag-4 (v0.14.0) is additive relative to Sprint-5 Tag-3 (v0.13.0):**

- The `wirelang.schemas.capability_policy_nats_kv_backend` module
  gains:
  - A new typed exception `CapabilityPolicyConflictError`
    (subclass of `CapabilityPolicyBackendError`) with three
    optional keyword-carrying fields: `key`, `expected_revision`,
    `actual_revision`. Byte-precise shape mirror of
    `SchemaRegistryConflictError` from
    `wirelang.schemas.registry_nats_kv_backend`.
  - New `NatsKvCapabilityPolicyBackend.get_with_revision(key)`
    method returning `Optional[Tuple[CapabilityPolicyRecord, int]]`.
    Mirror of
    `NatsKvSchemaRegistry.get_with_revision`.
  - New `NatsKvCapabilityPolicyBackend.get_with_revision_by_pair(registered_by, policy_id)`
    convenience wrapper. Mirror of `get_by_pair` semantics applied
    to the new CAS-pin helper.
  - New `NatsKvCapabilityPolicyBackend.put_with_revision(record, expected_revision)`
    method returning the new `int` revision; raises
    `CapabilityPolicyConflictError` on stale revision; raises
    `ValueError` on negative `expected_revision`; raises
    `TypeError` on non-record argument; raises
    `CapabilityPolicyBackendError("CAS-pin not supported")` if the
    KV adapter exposes neither `update(last=...)` nor
    `put(expected_revision=...)`.
  - New module-level helpers
    `_coerce_revision_from_entry`, `_kv_update_with_revision`,
    `_is_conflict_exception`, `_extract_actual_revision`, and
    constant `_CONFLICT_CLS_MARKERS = ("WrongLastSequence",
    "Conflict", "RevisionMismatch")`. Byte-precise shape mirrors of
    the schema-registry CAS-pin helpers. The helpers are inlined
    into the capability-policy module (not imported across
    modules) so the two backends can evolve independently.
  - Module `__all__` extended with `CapabilityPolicyConflictError`.
- All Sprint-5 Tag-2 LWW surfaces (`put` / `get` / `get_by_pair` /
  `delete` / `list_keys` / `snapshot` / `snapshot_registry`) are
  byte-unchanged. T-CPP-01..10 and the two auxiliary classes
  remain green. Existing callers that do not need lost-update
  protection continue to use `put` (LWW); they are not forced onto
  the CAS-pin path.
- The on-the-wire envelope schema
  (`wakir.wirelang.capability-policy-entry/1`) is byte-unchanged.
  CAS-pin operates on the same envelope shape as LWW; the only
  difference is the underlying KV operation
  (`update(last=...)` vs. `put(...)`). M-2 conformance preserved.
- The bucket configuration (`BUCKET_CONFIG`) is byte-unchanged.
  `history=5` already supports CAS-pin naturally (NATS-KV `update`
  with `last=` is unconditional on history depth ≥ 1). M-4
  conformance preserved (orthogonal to version axis).
- Cross-Review-Zone-1 (Identity-Substrate) non-touched: the
  CAS-pin path is a write-path concurrency contract, not a
  verifier contract. The four Z-1-K-Sprint-4 consensus points
  (kid-Resolver-Shape, JCS-Resolver-Lock, Curve-Choice = Ed25519,
  STRICT-Mode-Activation-Owner) remain byte-identical.
- Cross-Review-Zone-B (Kai bucket inventory) non-touched: no new
  bucket; the `wakir-capability-policies` bucket configuration is
  byte-unchanged; the Sprint-5 Tag-2 paired-update memo remains
  the canonical Z-B trigger.
- The Sprint-5 Tag-3 publisher-CLI `--capability-bucket` flag is
  read-only (`snapshot_registry()`) so the CAS-pin write path is
  not reachable from the operator CLI in Tag-4. A
  `--capability-bucket-cas-rotate` (or similar) subcommand surface
  is a Sprint-5 Tag-5+ candidate, explicitly NOT shipped in Tag-4.
- The Phase-1b Sprint-3 Tag-3 schema-registry CAS-pin surface is
  byte-unchanged. The Sprint-5 Tag-4 surface is a parallel module-
  local addition; the schema-registry helpers are not re-exported,
  re-shimmed, or refactored.
- The Phase-3 capability-policy watch-stream slot (full-snapshot
  only in Sprint-5 Tag-2/3/4; live-tail is Phase-3) and the
  Phase-3 multi-replica CAS-quorum slot (single-replica
  `replicas=1` in Sprint-5 Tag-2/3/4 configuration) remain
  reserved.
- Spec semver bump 0.13.0 → 0.14.0 reflects the additive minor
  change (M-2 §3.2 versioning policy: minor for additive). The
  bump is warranted by the new `CapabilityPolicyConflictError`
  exception class, the new `get_with_revision` /
  `get_with_revision_by_pair` / `put_with_revision` methods, the
  new §5.14 "CAS-pin operational contract (Sprint-5 Tag-4)"
  subsection, and the new §6.12 test inventory; no
  breaking-change to any consumer.

**Phase-2 Sprint-5 Tag-5 (v0.15.0) is additive over Sprint-5 Tag-4
(v0.14.0):**

- The Sprint-5 Tag-5 additions to
  `wirelang.schemas.capability_policy_nats_kv_backend` are purely
  additive surface:
  - New enum `CapabilityPolicyWatchOp` with values `PUT`, `DELETE`,
    `PURGE`. Byte-equal shape to the schema-registry
    `WatchOp` (Sprint-3 Tag-4); the class identity is module-local
    so the two backends can evolve independently.
  - New frozen dataclass `CapabilityPolicyWatchEvent(op, key, record,
    revision)` where `record` is `Optional[CapabilityPolicyRecord]`
    (`None` on DELETE / PURGE; the decoded record on PUT). The
    `entry → record` rename matches this module's canonical noun for
    the persisted unit.
  - New `NatsKvCapabilityPolicyBackend.watch()` async method
    returning a `_CapabilityPolicyWatchStreamHandle`.
  - New top-level `open_capability_policy_watch_stream(backend)`
    helper (rejects non-backend argument with `TypeError`).
  - New internal handle class `_CapabilityPolicyWatchStreamHandle`
    supporting both Shape-1 (native async iterator) and Shape-2
    (`await updates()` returning next-or-None) underlying watcher
    contracts.
  - New decoder `_decode_capability_policy_watch_update(update)`
    raising `CapabilityPolicyEnvelopeError` on poisoned envelope or
    unknown operation; reuses `_coerce_value_bytes` and
    `_envelope_to_record` byte-identical to the `get` and `snapshot`
    paths.
  - New watcher-opener helper
    `_open_capability_policy_watcher(kv)` supporting the
    `watchall()` (nats-py canonical) and `watch()` (mock-friendly)
    KV-handle conventions.
  - New live-tail consumer dataclass
    `LiveCapabilityPolicySnapshot(initial, last_revision=0)` with
    `__post_init__` defensive copy into a per-KV-key map (`_live:
    dict[str, CapabilityPolicyRecord]`), `apply(event)` for
    incremental PUT / DELETE / PURGE updates, `as_registry()` for a
    frozen Sprint-4 Tag-6 `CapabilityPolicyRegistry` view in sorted-
    key order, `records()` for a stable list of the underlying
    records, `last_revision` integer for revision monotonicity, and
    `from_backend(backend)` classmethod for the full-snapshot
    bootstrap.
  - Module `__all__` extended with `CapabilityPolicyWatchOp`,
    `CapabilityPolicyWatchEvent`,
    `LiveCapabilityPolicySnapshot`, and
    `open_capability_policy_watch_stream`.
  - Module docstring boundary-item "live tail reserved as a
    Phase-3 slot" rewritten to "added in Sprint-5 Tag-5
    (pattern-mirror on the schema-registry watch-stream, Sprint-3
    Tag-4)" with the orthogonality stamp (full-snapshot path
    remains supported and orthogonal).
- All Sprint-5 Tag-2 LWW surfaces (`put` / `get` / `get_by_pair` /
  `delete` / `list_keys` / `snapshot` / `snapshot_registry`) and all
  Sprint-5 Tag-4 CAS-pin surfaces (`get_with_revision` /
  `get_with_revision_by_pair` / `put_with_revision`,
  `CapabilityPolicyConflictError`, the five helper functions, and
  `_CONFLICT_CLS_MARKERS`) are byte-unchanged. T-CPP-01..10 + 2 aux
  (Sprint-5 Tag-2) and T-CPP-CAS-01..10 + 2 aux (Sprint-5 Tag-4)
  remain green. Existing callers that prefer the full-snapshot path
  continue to use `snapshot_registry`; they are not forced onto the
  watch-stream path.
- The on-the-wire envelope schema
  (`wakir.wirelang.capability-policy-entry/1`) is byte-unchanged.
  The watch-stream consumes the same envelope shape via the same
  `_envelope_to_record` decoder; the only watch-stream-specific
  decoding is the operation-kind + revision metadata, which is per-
  KV-entry not per-envelope. M-2 conformance preserved.
- The bucket configuration (`BUCKET_CONFIG`) is byte-unchanged.
  `history=5` already exposes the watch-stream naturally (NATS-KV
  `watchall` returns the initial replay over the live history depth
  before tailing the live stream). M-4 conformance preserved
  (orthogonal to version axis).
- Cross-Review-Zone-1 (Identity-Substrate) non-touched: the
  watch-stream is a producer surface for the
  `CapabilityPolicyRegistry`, not a verifier contract. The four
  Z-1-K-Sprint-4 consensus points (kid-Resolver-Shape, JCS-
  Resolver-Lock, Curve-Choice = Ed25519,
  STRICT-Mode-Activation-Owner) remain byte-identical. The gate
  decision is byte-equal regardless of registry source
  (`snapshot_registry` or watch-fed `as_registry`); T-CPP-WS-09
  cross-checks this against `check_registered_by_capability`.
- Cross-Review-Zone-B (Kai bucket inventory) non-touched: no new
  bucket; the `wakir-capability-policies` bucket configuration is
  byte-unchanged; the Sprint-5 Tag-2 paired-update memo remains the
  canonical Z-B trigger.
- The Sprint-5 Tag-3 publisher-CLI `--capability-bucket` flag is
  read-only (`snapshot_registry()`) and the Sprint-5 Tag-5
  watch-stream is NOT reachable from the operator CLI in Tag-5.
  A `--capability-bucket-watch` (or similar daemon-mode subcommand)
  is a Sprint-5 Tag-5+ candidate, explicitly NOT shipped in Tag-5.
  Operators who want the live tail consume the Python API directly.
- The Phase-1b Sprint-3 Tag-4 schema-registry watch-stream surface
  (`WatchOp`, `WatchEvent`, `NatsKvSchemaRegistry.watch`,
  `LiveSchemaSnapshot`, `open_watch_stream`) is byte-unchanged. The
  Sprint-5 Tag-5 surface is a parallel module-local addition; the
  schema-registry helpers are not re-exported, re-shimmed, or
  refactored. The Sprint-5 Tag-5 module-local copies preserve the
  evolution-decoupling stance set in Sprint-5 Tag-4 for the CAS-pin
  helpers.
- Phase-3 reservations preserved:
  - Watch-stream resumption / replay-from-revision
    (`watchall(..., resume_from=...)`) — nats-py supports it; the
    Sprint-5 Tag-5 wrapper exposes the underlying revision via
    `CapabilityPolicyWatchEvent.revision` and
    `LiveCapabilityPolicySnapshot.last_revision` but does not bake
    in a resume policy.
  - Multi-consumer fanout — the Tag-5 contract is single-consumer
    per asyncio task.
  - Cross-bucket capability-policy replication (analogous to
    Sprint-3 Tag-6 schema-registry replication) — Tag-5 lands the
    watch-stream substrate; the replication-tier composition is
    reserved.
  - Multi-replica CAS-quorum — `replicas=1` Sprint-5 Tag-2 bucket
    configuration is unchanged; CAS-pin operates on the single-
    replica revision counter; the watch-stream operates on the
    durable-history tail of the same single-replica stream.
  - Biscuit v3 binary-token interpretation of the policy envelope —
    the in-bucket JSON envelope shape is byte-unchanged.
- Spec semver bump 0.14.0 → 0.15.0 reflects the additive minor
  change (M-2 §3.2 versioning policy: minor for additive). The
  bump is warranted by the new `CapabilityPolicyWatchOp` enum, the
  new `CapabilityPolicyWatchEvent` dataclass, the new
  `LiveCapabilityPolicySnapshot` consumer dataclass, the new
  `NatsKvCapabilityPolicyBackend.watch` method, the new
  `open_capability_policy_watch_stream` top-level function, the
  new §5.14 "Watch-stream operational contract (Sprint-5 Tag-5,
  additive over Sprint-5 Tag-4)" subsection, and the new §6.13
  test inventory; no breaking change to any consumer.

## 9. Brand-Guide §9 sweep

This document has been swept against the Wakir Brand-Guide §9
(role-strings, no clear-name leakage in module / file / module-doc
content). The Sprint-4 Tag-1 additions (§5.8, §6.5, change-log
v0.6.0 entry, Phase-2 boundary updates) use role-strings only
(`Reza`, `Tomás`, `Mira`, `Aisha` appear in outbox documents and
optional cross-review memos, not in this spec; the spec mentions
only `wakir.*` URIs and module-path references).

The Sprint-4 Tag-3 additions (§5.9, §6.6, change-log v0.7.0 entry,
§1.2 Phase-2 Sprint-4 Tag-3 block, §7 cross-references update, §8
compatibility statement update) have been swept identically — only
role-strings, module-path references, `wakir.*` URIs, and IETF /
RFC references appear in the spec body. No external-tool clear-name
leakage and no internal-persona-clear-name leakage in the spec body.

The Sprint-4 Tag-4 additions (§5.10, §6.7, change-log v0.8.0 entry,
§1.2 Phase-2 Sprint-4 Tag-4 block, §5.3 lands-update,
§7 cross-references update — transport-fetch slot CONSUMED, §8
compatibility statement update for v0.7.0 → v0.8.0) have been swept
identically — only role-strings (none in this spec body), module-path
references (`wirelang.identity.aip_document_transport_fetch`,
`wirelang.identity.aip_https_backend`, `wirelang.identity.dns_anchor`),
`wakir.*` URIs (`_wakir-aip.`, `/.well-known/aip/`, `aip:web:`,
`wakir.wirelang.schema-registry-entry/1`), and IETF / RFC references
(RFC 8615 well-known namespace, RFC 8785 JCS, RFC 8032 Ed25519,
V-908 spec sections) appear in the spec body. No external-tool
clear-name leakage and no internal-persona-clear-name leakage in
the Tag-4 spec body additions.

The Sprint-4 Tag-5 additions (§5.11, §6.8, change-log v0.9.0 entry,
§1.2 Phase-2 Sprint-4 Tag-5 block, §5.3 lands-update — Sprint-4
Tag-5 added to the §5.3 header, AIP-document signature-verification
cache tier item moved from Phase-3-reserved to CONSUMED-in-Sprint-4-
Tag-5, §7 cross-references update — verification-cache tier slot
CONSUMED, §8 compatibility statement update for v0.8.0 → v0.9.0)
have been swept identically — only role-strings (none in this spec
body), module-path references
(`wirelang.identity.aip_signature_verification_cache`,
`wirelang.identity.verify_aip_signature`,
`wirelang.identity.aip_signing._jcs_canonicalize`),
`wakir.*` URIs (carried unchanged from prior tags), and IETF / RFC
references (RFC 8785 JCS, RFC 8032 Ed25519, V-908 spec sections)
appear in the spec body. No external-tool clear-name leakage and
no internal-persona-clear-name leakage in the Tag-5 spec body
additions.

The Sprint-4 Tag-6 additions (§5.12, §6.9, change-log v0.10.0 entry,
§1.2 Phase-2 Sprint-4 Tag-6 block, §5.3 lands-update — Sprint-4
Tag-6 added to the §5.3 header, `registered_by`-capability-gating
item moved from follow-up-Phase-2-slot (§5.8 Sprint-4 Tag-1
boundary) to CONSUMED-in-Sprint-4-Tag-6, §7 cross-references update
— `registered_by`-capability-gating slot CONSUMED, §8 compatibility
statement update for v0.9.0 → v0.10.0) have been swept identically
— only role-strings (none in this spec body), module-path references
(`wirelang.schemas.registered_by_capability`,
`wirelang.schemas.entry_signing`, `wirelang.schemas.registry_nats_kv_backend`),
`wakir.*` URIs (`wakir.wirelang.schema-registry-entry/1`,
`wakir-capability-policies` reserved bucket name, carried unchanged
from prior tags), and Python-stdlib/IETF/RFC references
(:mod:`fnmatch` grammar, RFC 8032 Ed25519, `wirelang/schemas/layer-3-capability-token.json`
Biscuit-v3 JSON envelope schema) appear in the spec body. No
external-tool clear-name leakage and no internal-persona-clear-name
leakage in the Tag-6 spec body additions.

The Sprint-5 Tag-1 additions (§5.13, §6.10, change-log v0.11.0 entry,
§5.3 publisher-CLI-capability-integration-slot CONSUMED, §5.6
publisher-CLI capability-flag cross-reference, §5.12 boundary
publisher-CLI item CONSUMED, §7 publisher-CLI-integration-of-Sprint-4-Tag-6-gate
slot CONSUMED, §8 compatibility statement update for v0.10.0 →
v0.11.0) have been swept identically — only role-strings (none in
this spec body), module-path references
(`wirelang.schemas.publisher_cli`, `wirelang.schemas.entry_signing`,
`wirelang.schemas.registered_by_capability`),
`wakir.*` URIs (`wakir-schemas` bucket name,
`wakir.wirelang.schema-registry-entry/1` envelope schema,
`wakir-capability-policies` reserved Phase-3 bucket name,
`wakir-schema-registry` CLI program name, carried unchanged from
prior tags), and IETF/RFC references (RFC 8032 Ed25519, RFC 8259
JSON, RFC 3339 timestamps, RFC 8785 JCS). The capability-registry
JSON file path examples use generic placeholder paths
(`~/.config/wakir/biscuit-root-1.seed`, `capability-registry.json`)
and the canonical operator examples (`wirelang-eng`, `biscuit-root-1`)
are role-strings consistent with prior tag conventions. No
external-tool clear-name leakage and no internal-persona-clear-name
leakage in the Tag-1 (Sprint-5) spec body additions.

The Sprint-5 Tag-2 additions (§5.14, §6.11, change-log v0.12.0
entry, §5.12 boundary persistent-capability-policy-distribution
item CONSUMED, §5.13 boundary persistent-capability-policy-
distribution item CONSUMED, §7 Phase-3-Reservation persistent
capability-policy-distribution slot CONSUMED, §8 compatibility
statement update for v0.11.0 → v0.12.0) have been swept identically
— only role-strings (none in this spec body), module-path references
(`wirelang.schemas.capability_policy_nats_kv_backend`,
`wirelang.schemas.registered_by_capability`,
`wirelang.schemas.registry_nats_kv_backend`,
`wirelang.schemas.publisher_cli`, `wirelang.schemas.entry_signing`),
`wakir.*` URIs (`wakir-capability-policies` new bucket name,
`wakir.wirelang.capability-policy-entry/1` new envelope schema,
`wakir-schemas`, `wakir-aip-cache`, `wakir-ftd-cache`,
`wakir-ftd-poisoned`, `wakir-schema-registry-entries`,
`wakir-federation-routes` carried unchanged from prior tags), and
IETF/RFC references (RFC 3339 timestamps, RFC 8259 JSON, RFC 8785
JCS — though the persistent policy envelope is NOT a JCS-anchored
digest at the policy-envelope axis). The persistent-bucket key
prefix (`capability-policies/`), the policy-pair format
(`capability-policies/<registered_by>/<policy_id>`), the canonical
operator role-strings (`wirelang-eng`, `biscuit-root-1`,
`federation-eng`, `biscuit-fed-1`), and the canonical policy_id
strings (`default`, `tier-1-ingress`, `wire-scope`,
`identity-scope`, `alpha`, `beta`, `gamma`) are role-strings /
operator-side identifiers consistent with prior tag conventions.
No external-tool clear-name leakage and no internal-persona-clear-name
leakage in the Tag-2 (Sprint-5) spec body additions.

The Sprint-5 Tag-3 additions (§5.13 "Bucket policy source (Sprint-5
Tag-3)" subsection, §6.10 "Bucket policy source tests" addendum,
change-log v0.13.0 entry, §5.13 boundary item "future
`--capability-bucket`" CONSUMED, §5.14 boundary item "publisher-CLI
integration" CONSUMED, §7 Phase-3-Reservation "publisher-CLI
`--capability-bucket` integration" CONSUMED, §8 compatibility
statement update for v0.12.0 → v0.13.0) have been swept identically
— only module-path references (`wirelang.schemas.publisher_cli`,
`wirelang.schemas.capability_policy_nats_kv_backend`,
`wirelang.schemas.registered_by_capability`), `wakir.*` URIs
(`wakir-capability-policies` carried unchanged from Sprint-5 Tag-2;
no new bucket added), the new flag names (`--capability-bucket`,
`--capability-bucket-connect-url`), the new receipt field name
(`gate_policy_source`), the new receipt-source values (`"file"`,
`"bucket"`), and the canonical operator examples (`wirelang-eng`,
`biscuit-root-1`, `nats://127.0.0.1:4222` connect URL placeholder)
are role-strings / operator-side identifiers consistent with prior
tag conventions. No external-tool clear-name leakage and no
internal-persona-clear-name leakage in the Tag-3 (Sprint-5) spec
body additions.

The Sprint-5 Tag-4 additions (§5.14 "CAS-pin operational contract
(Sprint-5 Tag-4)" subsection, §6.12 capability-policy CAS-pin test
inventory, change-log v0.14.0 entry, §5.14 boundary item "future
CAS-pinned upsert path" CONSUMED, §7 Phase-2 capability-policy
CAS-pin slot CONSUMED, §8 compatibility statement update for
v0.13.0 → v0.14.0) have been swept identically — only module-path
references (`wirelang.schemas.capability_policy_nats_kv_backend`,
`wirelang.schemas.registry_nats_kv_backend`,
`wirelang.schemas.registered_by_capability`), `wakir.*` URIs
(`wakir-capability-policies` carried unchanged from Sprint-5 Tag-2;
no new bucket added), the new exception class name
(`CapabilityPolicyConflictError`), the new method names
(`get_with_revision`, `get_with_revision_by_pair`,
`put_with_revision`), the new module-level helper names
(`_coerce_revision_from_entry`, `_kv_update_with_revision`,
`_is_conflict_exception`, `_extract_actual_revision`,
`_CONFLICT_CLS_MARKERS`), the conflict-class-name markers
(`WrongLastSequence`, `Conflict`, `RevisionMismatch`), and the
canonical operator examples (`wirelang-eng`, `tier-1-ingress`,
`rollover`, `biscuit-root-1`, `biscuit-root-2`) are role-strings /
operator-side identifiers / public API names consistent with prior
tag conventions. No external-tool clear-name leakage and no
internal-persona-clear-name leakage in the Tag-4 (Sprint-5) spec
body additions.

The Sprint-5 Tag-5 additions (§5.14 "Watch-stream operational
contract (Sprint-5 Tag-5, additive over Sprint-5 Tag-4)" subsection,
§5.14 "Boundary: Sprint-5 Tag-5 does NOT ship (explicit)" subsection,
§6.13 capability-policy watch-stream test inventory, change-log
v0.15.0 entry, §5.14 boundary item "live tail reserved as a Phase-3
slot" CONSUMED, §7 Phase-3 capability-policy watch-stream slot
CONSUMED, §7 "No watch-stream on the capability-policy bucket"
boundary CONSUMED, §8 compatibility statement update for
v0.14.0 → v0.15.0) have been swept identically — only module-path
references (`wirelang.schemas.capability_policy_nats_kv_backend`,
`wirelang.schemas.registry_nats_kv_backend`,
`wirelang.schemas.registered_by_capability`), `wakir.*` URIs
(`wakir-capability-policies` carried unchanged from Sprint-5 Tag-2;
no new bucket added), the new public class names
(`CapabilityPolicyWatchOp`, `CapabilityPolicyWatchEvent`,
`LiveCapabilityPolicySnapshot`), the new public function name
(`open_capability_policy_watch_stream`), the new internal helper /
handle names (`_CapabilityPolicyWatchStreamHandle`,
`_decode_capability_policy_watch_update`,
`_open_capability_policy_watcher`), the operation-kind markers
(`PUT`, `DELETE`, `PURGE`), the canonical operator examples
(`wirelang-eng`, `orchestrator-eng`, `biscuit-root-1`,
`biscuit-root-2`, `biscuit-root-r1`, `biscuit-root-r2`,
`rotation-1`, `rotation-2`, `default`), and the nats-py adapter
shape names (`watchall`, `watch`, `updates`, `stop`, `__aiter__`,
`__anext__`) are role-strings / operator-side identifiers / public
API names consistent with prior tag conventions. No external-tool
clear-name leakage and no internal-persona-clear-name leakage in
the Tag-5 (Sprint-5) spec body additions.

— End of spec —
