<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

---
doc: capability-token-layer-snapshot
version: 0.1.0
status: snapshot
date: 2026-05-16
author: Reza Tehrani (Dev-Engineering-2)
audience: priya-cto, mira-ceo, phase-2-roadmap-refresh
purpose: Inventar des aktuellen Standes im AIP+Biscuit-Capability-Token-Layer für Phase-2-Roadmap-Refresh.
---

# AIP + Biscuit Capability-Token-Layer — Sprint-Item-Snapshot

> Stand 2026-05-16. Diese Note ist ein **Inventar**, kein
> Architektur-Vorschlag. Sie listet was in Sprint-7..10 +
> Sprint-Pengine-7..12 + Multi-Org-Federation-Bring-up substanziell
> live ging und was als Open-Item für Phase-2c-Closeout bzw.
> Phase-3a bleibt.

## 1. Live-Substanz (in main, Tip `3350d2dd`)

### 1.1 Spec-Substrate

| Artefakt | Status | Verifikations-Anker |
|---|---|---|
| `wirelang/specs/wirelang-spec-v0-2.md` | v0.2.1 (heute, §13 Subscribe-Mode), v0.2.0 Phase-1a-Closeout | §6 Layer-3 Trust |
| `wirelang/specs/layer-3-capability-token.md` | Phase-1a-stable | §1 Biscuit v3.3 + AIP draft-prakash-aip-00 |
| `wirelang/specs/datalog-caveat-vocabulary.md` | v0.1 (18+2 Prädikate) | Phase-1a-Tag-3 Vocabulary |
| `wirelang/specs/datalog-caveat-vocabulary-phase-2.md` | Phase-1b-Tag-15 ratified | N1/N2/R/P-Classification + Caveat-Set-Canonicalisation + TV-W-2 Pin-Stability |
| `wirelang/specs/identity-substrate.md` | v0.29.0 | §5 SPIFFE-ID-Binding (Sprint-7-Pfad-B + Sprint-10-Tag-7-Zone-B) |
| `wirelang/specs/schema-registry-spec.md` | Phase-1a-stable | OTS-anchored Schema-Registry |
| `wirelang/schemas/aip-document.json` | JSON-Schema 2020-12 | normative for AIP-document shape |
| `wirelang/schemas/datalog-caveat.json` | JSON-Schema 2020-12 | normative for caveat shape |
| `wirelang/schemas/layer-3-capability-token.json` | JSON-Schema 2020-12 | normative for token JSON projection |

### 1.2 Krypto-/Identity-Substrate

| Modul | Funktion | Sprint-Anker |
|---|---|---|
| `wirelang/identity/key_derivation.py` | BIP-32 / SLIP-0010 Sub-Key-Ableitung pro persona-idx/spawn-counter | Sprint-3 |
| `wirelang/identity/aip_document.py` | AIP-Document-Konstruktion mit `biscuit_root_pubkey` Wakir-Extension | Sprint-3..5 |
| `wirelang/identity/aip_signing.py` | Ed25519-Signatur über JCS-canonical Body | Sprint-3..5 |
| `wirelang/identity/kid_resolver.py` | KID → Public-Key Resolver (DID + AIP) | Sprint-6..7 |
| `wirelang/identity/federation_resolver.py` | Cross-Trust-Domain Bundle-Endpoint-Resolver | Sprint-7-Pfad-B |
| `wirelang/identity/ftd_verifier.py` | FTD (Federated-Trust-Domain) Verifier | Sprint-7-Pfad-B Tag-3..6 |
| `wirelang/federation/spire_fed_bundle_live_https_fetcher.py` | Live-HTTPS-Bundle-Fetcher (Phase-2c TLS-posture) | Sprint-7-Pfad-B Tag-6 PR #59 |
| `wirelang/federation/multi_org_substrate.py` | Multi-Org-Federation-Substrate | Sprint-7 Tag-1..2 |
| `wirelang/federation/n2_evaluator.py` | N2-Federation-Prädikat-Evaluator | Phase-1b-Tag-15 V-908-Federation-Extension |

### 1.3 Token-Lifecycle

| Komponente | Status | Anker |
|---|---|---|
| Authority-Block-Signierung Ed25519 | live | Sprint-3 + AIP-Document-Test-Fixtures |
| Append-Block-Attenuation | live | Sprint-8 caveat-override-export + Sprint-9 caveat-override-Tests |
| Sealing (irrevocable) | live (Biscuit-v3-Default) | Sprint-3 |
| Capability-Mint pro Component-Type | live | Identity-Substrate-Spec §5.6 |
| Caveat-Vocabulary v0.1 (18+2 Prädikate) | live | datalog-caveat-vocabulary.md |
| Phase-2-Vocabulary (N1/N2/R/P-Classification) | ratified Phase-1b-Tag-15 | datalog-caveat-vocabulary-phase-2.md |
| `peer_org` + `federation_route` N2-Federation-Prädikate | live | N2-Evaluator + Multi-Org-Substrate |
| Token-Hash-Commitment in `caprefs` Frame-Attr | live | Wirelang §4 Wire-Format |
| Marker-Stack-KV (Marker-2D/2E/2F + Marker-Stack) | live | Sprint-8 Tag-2..4 |
| Multi-Marker-Policy | live | Sprint-8 Tag-3 PR-merged |
| Durable-Ledger OTS-Anker | live | Sprint-9 Tag-2 |
| Operator-CLI-Replicator | live | Sprint-9 Tag-3 |

### 1.4 AIP-Document-Anchoring + DID

| Funktion | Status |
|---|---|
| DID-Document Publication (`did:web`, `https://wakir.dev/.well-known/did/<role>/v<N>.json`) | substrate-ready, Phase-2-Live-Hosting Open-Item |
| AIP-Document `draft-prakash-aip-00` §2.3 conformant + `biscuit_root_pubkey` Wakir-Extension | live |
| Persona-Hash-Commitment (V-907 Phase 3 `personahash` Frame-Attr) | live |
| Persona-Pin-Commitment (`personapin` Frame-Attr) | live |
| TEE-Attestation-Reference (`attestationref` V-904 Phase 3) | substrate-ready, Hardware Open-Item für Phase-3 |
| Image-Digest-Pin (`imagedigest` Phase-1b) | live |

### 1.5 SPIFFE/SPIRE-Integration

| Komponente | Status | Anker |
|---|---|---|
| SPIFFE-ID-Pfad-Form `spiffe://<td>/agent/<persona-slug>/<persona-hash-12>` | live in Spec §5 | Identity-Substrate-Spec v0.29.0 |
| SPIFFE-ID-Pfad-Form `spiffe://wakir.<org_id>/persona/<persona_id>` (Sprint-Pengine-Selin-Konvention) | live in Engine-Modul | Cross-Review Zone-L 2026-05-15 |
| Workload-API-Surface via `real_spiffe_workload_api.py` | live | Sprint-8 Tag-1 PR-merged |
| Bilateral-Federation-Substrate | live | Sprint-Tag-8 Kai PR #76 (Bug-39 Fix) |
| Resolver-Trust-Mode-Selector | live | Sprint-Tag-8 PR #76 |
| Production-Quadlet persona-tomas | live | Sprint-Tag-8 PR #76 |
| NodeAttestor `join_token` (mode-symmetric single-org + federation) | live für Phase-2c | Sprint-10-Tag-7 PR #71 Option B (Bug-37) |
| NodeAttestor `x509pop` Phase-3-Migration | Tracking-Note `docs/decisions/phase-3-nodeattestor-migration.md` | heute geschrieben |

## 2. Open-Items für Phase-2c-Closeout (vor Phase-3a)

### 2.1 Spec-Konsolidierungs-Open-Items

- **OI-CT-1 — Wirelang-Spec v0.2.1 Subscribe-Mode (§13) PR-Merge.**
  Heutige Spec-Änderung; Cross-Review-Bedarf mit Tomás
  (Bridge-Forward-Pipe-Producer-Surface) + Selin/Pengine
  (Subscribe-Loop-Surface-Declaration).
- **OI-CT-2 — Phase-2 Vocabulary-Bump in Wirelang-Spec-Body.**
  `datalog-caveat-vocabulary-phase-2.md` ist Phase-1b-Tag-15
  ratified; Wirelang-Spec-§6.4 referenziert es aber als
  "Phase-2 sketch" in v0.2.0-Body. Spec-Body-Update als v0.2.2
  möglich (additiv, keine Wire-Änderung).
- **OI-CT-3 — Zone-3 OTS-Schema-Anker Consensus-Stamp.**
  Wirelang-Spec §9 nennt Zone-3 als "consensus stamp pending at
  v0.2 publication time". WAT × Wirelang Cross-Review-Zone, Owner
  Tomás (WAT) + Reza (Schema-Registry). Phase-2c-Closeout-Item.

### 2.2 Implementations-Open-Items

- **OI-CT-4 — Full gRPC SVID-Fetch im Persona-Engine.**
  Aktuell nur Socket-Probe (Sprint-Pengine-8 Zone-L). Full
  SVID-Fetch erfordert `grpcio` + `cryptography` wheels (~80MB
  native code). Cross-Review Zone-L 2026-05-15 hat das auf
  Sprint-Pengine-9-axis verschoben; Bug-40 Sprint-Pengine-11
  Graceful-Fallback ist als Vorstufe drin (`0.4.1-pilot`).
- **OI-CT-5 — Phase-3 NodeAttestor-Migration zu x509pop.**
  Tracking-Note `phase-3-nodeattestor-migration.md` (heute);
  Trigger T-1/T-2/T-3 dokumentiert; ADR-Slot pending bis Trigger
  realistisch.
- **OI-CT-6 — Bridge-Forward-Pipe-Mode-Migration zu JetStream.**
  v0.2.1 §13.5 dokumentiert dass `wakir-bridge-forward` aktuell
  `nc.publish` (core) ist. Adapter B (Producer-Rewrite zu
  `js.publish`) ist Phase-2c-Closeout-Target. Bis dahin: Adapter A
  (Stream-Mirror) oder Subscribe-Loop bleibt auf `core`-Surface
  (heute der Fall, vgl. `nats_subscribe_loop.py`).
- **OI-CT-7 — DID-Web-Document Live-Hosting.**
  `did:web`-Documents sind substrate-ready (AIP-Document-Modul);
  Live-Hosting unter `https://wakir.dev/.well-known/did/<role>/
  v<N>.json` ist DevOps-Track Open-Item (Cloudflare-Pages-Site +
  `.well-known/`-Routing).
- **OI-CT-8 — PeerSvidVerifier Live-Implementation.**
  JWKS-parsing JWT-SVID-Verifier auf Basis `cryptography`-Package.
  Bridge-Slot bereits dort (Sprint-7-Pfad-B Tag-6 Folge-Item), Live-
  Implementation für end-to-end echte Cross-Trust-Domain-Validation
  fehlt.

### 2.3 Vocabulary-Growth-Open-Items

- **OI-CT-9 — V-911 Pre-Commit-Veto-Window Vocabulary.**
  V-911 ist Tomás-Domäne (Owner per Domain-Spezialisierungs-Tabelle).
  Cross-Review-Bedarf wenn V-911-Vocabulary in Wirelang-Layer-3
  einschlägt.
- **OI-CT-10 — Phase-3 V-908-Federation-Extension Vocabulary-Wachstum.**
  `peer_org` + `federation_route` sind in Phase-2-Vocab live;
  Phase-3 Multi-Org-Marketplace könnte zusätzliche N2-Prädikate
  fordern (z.B. `marketplace_listing`, `cross_org_consent`).
  Vorzeitig spezifizieren wäre Spec-Paralysis; Trigger ist erstes
  Phase-3a-Sprint mit Multi-Org-Marketplace-Substanz.

## 3. Sprint-Cadence-Bezug

### 3.1 Sprint-Pengine-Welle (Doppelbetrieb / Persona-Engine)

- Sprint-Pengine-7..12 (2026-05-14..15) — Selin-Hand-Implementation
  der echten persona-engine `0.2.0-pilot` → `0.4.2-pilot`. Sub-state
  taube sync-engine-Heartbeat-Loop in Pengine-10 → real-async
  subscribe-loop in Pengine-12 (Bug-41 CLI-async-wrap).
- Sprint-Pengine-13 (heute morgen) — Bug-42 Subscribe-Loop-Empfangs-
  Lücke. **Heute mit §13 Subscribe-Mode-Klausel spec-substrate-
  geklärt.** Implementations-Pfad ist Strategy-Hand-Mira-Scope
  (vermutlich Adapter A Stream-Mirror oder Adapter C
  Subscribe-side fallback als Sprint-Übergangs-Pattern).

### 3.2 Sprint-7-Pfad-B-Welle (Federation)

- Sprint-7-Pfad-B Tag-1..6 (2026-05-12..15) — Multi-Org-Federation-
  Substrate, SPIFFE Cross-Trust-Domain-Bridge, Capability-Attenuation-
  Chain-Verifier, Live-Counterpart-Adapter (PR #59 merged).
- Sprint-10 Tag-4..8 — DevOps-Track-Bring-up; Bug-37 NodeAttestor-
  Wahl (heute Phase-3-Migration-Note geschrieben), Bug-38 federation-
  mode acceptance-script, Bug-39 + Bug-36-Härtung (PR #76 merged).

### 3.3 Capability-Token-Bursts auf WAT

WAT × Wirelang Cross-Review-Zone-2 ist seit Phase-1a-Tag-9 (commit
`338e007`) consensus-stamped. Four-tuple Leaf-Projection
(`specs/wat-leaf-projection.md`) ist die Token-Burst-Anker-Form.
Phase-2c-Closeout-Cross-Review-Bedarf:

- Marker-Stack-KV-Anker (Sprint-8 Tag-4 PR-merged) in WAT-Leaf-Projection
  reflektieren?
- Durable-Ledger OTS-Anker (Sprint-9 Tag-2) in WAT-Layer-4 Merkle-
  Anker konsolidieren?

**Owner-Empfehlung:** Cross-Review-Zone-2 (Tomás-WAT-Owner +
Reza-Wirelang-Owner) in Phase-2c-Closeout-Welle (Sprint-12+).

## 4. Phase-2-Roadmap-Refresh-Vorschlag

Aus Capability-Token-Layer-Sicht sind drei Phase-2c-Closeout-Items
**must-have** vor Phase-3a-Start:

| Item | Owner | Effort-Schätzung |
|---|---|---|
| OI-CT-1 §13 Subscribe-Mode-Spec PR-Merge + Cross-Review | Reza (Spec) + Tomás (Bridge-Forward-Producer) + Selin (Subscribe-Loop) | 1 Tag |
| OI-CT-6 Bridge-Forward-Mode-Migration zu JetStream (Adapter B) | Tomás (Producer-Rewrite) | 2 Tage |
| OI-CT-3 Zone-3 OTS-Schema-Anker Consensus-Stamp | Reza + Tomás Cross-Review | 1 Tag |

Drei Phase-2c-Closeout-Items sind **nice-to-have** (würden
Phase-3a-Start nicht blockieren):

| Item | Owner | Effort-Schätzung |
|---|---|---|
| OI-CT-2 Phase-2 Vocabulary-Bump in Wirelang-Spec-Body (v0.2.2) | Reza | 0.5 Tag |
| OI-CT-4 Full gRPC SVID-Fetch im Persona-Engine | Selin (Sprint-Pengine-9-axis) | 3 Tage |
| OI-CT-8 PeerSvidVerifier Live-Implementation | Reza | 2 Tage |

Drei sind **Phase-3a-Triggered** (kein Phase-2c-Closeout-Bedarf):

| Item | Trigger |
|---|---|
| OI-CT-5 Phase-3 NodeAttestor-Migration zu x509pop | Trigger T-1/T-2/T-3 in `phase-3-nodeattestor-migration.md` |
| OI-CT-7 DID-Web-Document Live-Hosting | Phase-3a Multi-Org-Onboarding |
| OI-CT-9/10 V-911 + V-908 Vocabulary-Wachstum | Phase-3a Multi-Org-Marketplace-Substanz |

## 5. Risiko-Disposition

- **Spec-Drift-Risiko Wirelang vs. Identity-Substrate-Spec:**
  Beide Specs nutzen v0.29.0 (Identity-Substrate) bzw. v0.2.0
  (Wirelang) — keine Versionierungs-Drift, weil sie unabhängige
  Versions-Achsen führen. Heute v0.2.1-Bump ist additiv (§13);
  Identity-Substrate-Spec bleibt v0.29.0.
- **AIP-Draft-Expiry-Risiko:** `draft-prakash-aip-00` expires
  2026-09-28 (verifiziert P7-stamp 2026-05-06). Phase-2c muss vor
  Expiry entscheiden: draft -01 adoptieren (wenn published bis dahin)
  oder Freeze auf -00 als Wakir-Internal-Profile. Mira-Decision-
  Punkt vor 2026-09-01.
- **Biscuit-v3.3-Stabilität:** Biscuit v3.3 spec-stable per
  eclipse-biscuit `SPECIFICATIONS.md` (verifiziert P7-stamp
  2026-05-06). Kein Migrations-Risiko in Phase-2.

## 6. Quellen

- Wirelang Spec v0.2.0: `wirelang/specs/wirelang-spec-v0-2.md`
- Wirelang Spec v0.2.1 §13 Subscribe-Mode: heutiger Bump
- Layer-3 Spec: `wirelang/specs/layer-3-capability-token.md`
- Identity-Substrate Spec v0.29.0: `wirelang/specs/identity-substrate.md`
- Phase-3 NodeAttestor-Migration Tracking: `docs/decisions/phase-3-nodeattestor-migration.md`
- Bridge-Forward-Pipe v1: `wirelang/specs/bridge-forward-pipe-v1.md`
- Sprint-10-Tag-7 Zone-B Cross-Review: `agents-workspaces/reza/outbox/2026-05-15-reza-zone-b-cross-review-kai-tag-7-bug-37.md`
- Sprint-7-Pfad-B Tag-6 Live-Counterpart: `agents-workspaces/reza/outbox/2026-05-15-reza-sprint-7-pfad-b-tag-6-live-counterpart.md`

— Reza
