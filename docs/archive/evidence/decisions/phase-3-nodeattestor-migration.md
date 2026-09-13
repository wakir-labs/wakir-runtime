<!--
SPDX-License-Identifier: CC-BY-4.0
Copyright (c) 2026 Wakir Labs contributors
-->

---
doc: phase-3-nodeattestor-migration
version: 0.1.0
status: tracking-note
date: 2026-05-16
author: Reza Tehrani (Dev-Engineering-2)
audience: kai-devops, priya-cto, mira-ceo, future-adr-author
relates-to:
  - decisions/topology-bilateral-federation.md
  - wirelang/specs/identity-substrate.md
  - sprint-10-tag-7-pr-71 (Bug-37 NodeAttestor-Wahl)
  - zone-b-cross-review-2026-05-15 (APPROVE-with-phase-3-migration-note)
---

# Phase-3 NodeAttestor Migration — Tracking Note

> **Status:** Tracking-Note, **kein** ADR.
> Reza-Zone-B-Cross-Review 2026-05-15 hat Kai's Sprint-10-Tag-7 Bug-37-Fix
> (Option B, mode-symmetric `join_token`) **APPROVED with phase-3
> migration note**. Diese Note materialisiert den Phase-3-Migrations-
> Pfad als Trigger-Anker und Schritte-Skizze, damit Phase-3-Planung
> (frühestens Sprint-12+ bzw. Phase-2c-Closeout) eine konkrete
> Diskussions-Grundlage hat.
> Eine formale ADR-Vorlage entsteht erst, wenn ein Phase-3-Trigger
> (§2) realistisch wird; bis dahin ist `join_token` operationell
> günstiger als x509pop und spec-konform.

## 1. Ist-Zustand (Sprint-10-Tag-7, 2026-05-15)

| Komponente | Mode-Symmetric Konfiguration |
|---|---|
| `spire-server-{orbit,wakir}.conf` `NodeAttestor "join_token"` | aktiv beide Modes (single-org + federation) |
| `spire-agent-{orbit,wakir}.conf` `NodeAttestor "join_token"` | aktiv beide Modes |
| `compose/spire-federation.yaml` Quadlet `-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER` | Bootstrap-Script step-6i `sed -i` injiziert Token |
| `wakir-pilot-bootstrap.sh` step-6i `spire-server token generate` | single-use Token, mode-agnostic |

**Konsequenz für Wakir-Identity-Substrate-Spec v0.29.0 §5:**
SPIFFE-ID-Form, Trust-Domain-URI-Form und Capability-Mint-Surface-
Autorität sind **plugin-agnostisch**. NodeAttestor-Wahl ist eine
DevOps-Track-Konfiguration (§5.7 explizit: "SPIRE-server + SPIRE-agent
operational topology"), **nicht** eine Spec-Substanz. Die hier
dokumentierte Migration berührt §5 daher **nicht**.

## 2. Phase-3-Migrations-Trigger (load-bearing)

Phase-3-Migration zu einem self-attesting NodeAttestor-Plugin ist
gerechtfertigt, sobald **eine** der folgenden drei Bedingungen
realistisch wird. Vor diesem Punkt ist `join_token` operationell
günstiger.

### Trigger T-1 — N>>1 Agent-Skalierung

Mehrere Agent-Instanzen pro Trust-Domain (z.B. workload-Replicas,
Auto-Scaling-Gruppen, Multi-Replica Persona-Container).

- **Schwelle:** ≥3 Pilot-Partner mit je ≥3 VMs ODER
  Auto-Scaling-Requirement irgendwo im Stack.
- **Friction-Quelle:** `join_token` ist single-use; Operator-Hand-
  Generation pro Agent-Bootstrap skaliert nicht.
- **Mess-Anker:** Anzahl `spire-server token generate`-Aufrufe pro
  Woche im Operator-Log. Wenn >10/Woche → Trigger T-1 eskaliert.

### Trigger T-2 — Auto-Re-Imaging (Immutable-Infra)

Pet→Cattle-Pattern: VMs werden bei Updates komplett neu provisioniert
statt gepatcht.

- **Schwelle:** Wakir-Pilot-Topologie wechselt von Proxmox-Manual-
  Provision zu Image-Based-Auto-Provision (z.B. Packer + Ignition
  + cloud-init).
- **Friction-Quelle:** Operator-Hand-Token-Generation bricht
  Self-Healing-Loops.
- **Mess-Anker:** Existenz eines Image-Build-Pipelines im
  Wakir-Onboarding-Repo (heute: nicht existent).

### Trigger T-3 — Audit-Provenance-Anforderung

Anforderung aus Compliance / Pilot-Partner-Audit-Vertrag, dass
Agent-Identität kryptographisch beweisbar an Hardware-Identität
oder durable Schlüssel-Material gebunden ist.

- **Schwelle:** Erster Pilot-Partner-Vertrag mit Audit-Klausel
  "agent identity must be provable via cryptographic attestation
  (not bearer token)".
- **Friction-Quelle:** `join_token` ist Bearer-Token; wer den
  Token besitzt, attestiert. Audit-Provenance fordert ein
  Key-Material-Besitz-Beweis-Pfad.
- **Mess-Anker:** Audit-Klausel im Vertrags-Template (zu prüfen
  bei erstem Enterprise-Pilot-Partner ab Phase-3a).

## 3. Migrations-Pfad zu x509pop

Empfohlene Option ist `x509pop` (Mira-ursprüngliche Empfehlung in
Bug-37-Skizze 2026-05-15). Alternative Optionen (cloud-provider-
attestor, SSH-cert) sind in der Zone-B-Cross-Review §3 dokumentiert
und für aktuellen On-Prem-Pilot **nicht** anwendbar.

### 3.1 Plugin-Substrat-Anforderungen

| Anforderung | Implementations-Pfad |
|---|---|
| X.509-CA für Agent-Identitäts-Zertifikate | Phase-3-Provisioning-Pipeline; CA-Wurzel als Wakir-Onboarding-Artefakt |
| Per-Agent `agent.crt` + `agent.key` | Image-Build-Time-Injection oder Bootstrap-Pipeline mit Sealed-Secret-Pattern |
| `ca_bundle_path` auf SPIRE-Server | Identisch zum Federation-Bundle-CA, getrennter Vertrauensanker |
| Cert-Rotation-Cadence | ≤90 Tage; Pre-Expiry-Rotation via SPIRE-CLI oder externer Cert-Manager |

### 3.2 Migrations-Schritte (Phase-3 Sprint-N Skizze)

1. **Pre-Step — ADR-Slot eröffnen.** "NodeAttestor-Production-Migration"
   wird ein ADR (Slot-Nummer in Folge ADR-0058+). Owner: Kai-DevOps
   in Koordination mit Reza (Spec-Konsistenz) + Priya (Architektur-
   Approval).
2. **Schritt 1 — CA-Auswahl.** Existierende Wakir-CA-Infrastruktur
   prüfen (Federation-Bundle-CA, wakir-pilot-self-signed, oder neue
   dedizierte Agent-Attestation-CA). Entscheidung: separate CA für
   Agent-Attestation, weil Federation-Bundle-CA ein anderer Trust-
   Anchor ist (Cross-Trust-Domain) vs. Intra-Trust-Domain-Attestation.
3. **Schritt 2 — Cert-Provisioning-Pfad.** Image-Build-Time-Injection
   vs. Bootstrap-Pipeline-Injection. Empfehlung: Bootstrap-Pipeline
   mit Sealed-Secret-Pattern (cert + key liegen verschlüsselt im
   Provisioning-Repo, Decryption-Key auf VM via TPM-sealed-secret
   oder per Operator-Hand). Image-Build-Time-Injection erfordert
   Per-VM-Image-Build, das bricht Auto-Scaling.
4. **Schritt 3 — Plugin-Config-Switch parallel.**
   `spire-server-{orbit,wakir}.conf` und `spire-agent-{orbit,wakir}.
   conf` bekommen `x509pop`-Plugin-Block **parallel** zum existierenden
   `join_token`. SPIRE unterstützt Multi-Plugin-NodeAttestor;
   Agent-Side-Selektor entscheidet welcher Plugin pro Agent gilt.
5. **Schritt 4 — Schrittweise Agent-Migration.** Pro Trust-Domain
   einen Agent zu `x509pop` migrieren, Smoke-Test, dann nächsten.
   Old-Agents bleiben auf `join_token`. **Kein Big-Bang.**
6. **Schritt 5 — Old-Token-Path-Disable.** Nach Migration aller
   Agents: `join_token`-Plugin aus `spire-server`-Config entfernen,
   `spire-server token generate`-Workflow aus Bootstrap-Script
   entfernen. Final commit closing the loop.
7. **Schritt 6 — Cert-Rotation-Runbook.** Operator-Runbook für
   Cert-Rotation (vor Expiry, post-CA-Rotation). Heimat:
   `docs/decisions/spire-cert-rotation-runbook.md`.
8. **Schritt 7 — Spec-Touch.** Wakir-Identity-Substrate-Spec v0.30.0
   §5.7 ergänzen um expliziten NodeAttestor-Plugin-Anker (heute
   plugin-agnostisch; Phase-3 macht Plugin-Wahl spec-sichtbar im
   §5.7-DevOps-Track-Item-Catalog). Vocabulary-Wachstum, **additiv**
   per Wirelang §8 Forward-Compat.

### 3.3 Acceptance-Gates

| Gate | Kriterium |
|---|---|
| G-1 Hermetic-Test | x509pop-Plugin attestiert Test-Agent gegen Test-CA in Hermetic-Sandbox |
| G-2 Live-Smoke | Beide Pilot-VMs (orbit + wakir oder Phase-3-Äquivalent) attestieren via x509pop, beide bekommen Agent-SVID |
| G-3 Workload-API-Surface unverändert | Workloads bekommen identische SVID-Form (`spiffe://<td>/...`); `wirelang/adapters/real_spiffe_workload_api.py` Surface unverändert |
| G-4 Federation unverändert | Cross-Trust-Domain-Bundle-Exchange läuft (Federation und NodeAttestor sind orthogonal, vgl. Zone-B-Cross-Review §2) |
| G-5 Cert-Rotation | Pre-Expiry-Rotation erfolgreich (Agent verliert keinen SVID-Heartbeat) |
| G-6 Audit-Trail | SPIRE-Server-Log zeigt Attestation-Provenance pro Agent (Audit-Provenance-Anforderung Trigger T-3 erfüllt) |

### 3.4 Backout-Plan

Falls Phase-3-Migration scheitert (Acceptance-Gate G-2 oder G-5
nicht reproduzierbar):

1. Parallel-Plugin-Config (Schritt 3) erlaubt instant Backout:
   einzelne Agents zurück zu `join_token` migrieren.
2. **Kein** State-Drift, weil Agent-SVID-Rotation orthogonal zur
   NodeAttestor-Wahl ist (Zone-B-Cross-Review §1.3 Frage 3).
3. Falls Massen-Backout notwendig: `x509pop`-Plugin-Block aus
   Configs entfernen, Bootstrap-Script step-6i wieder aktivieren.
4. Backout-Drill-Trigger: Phase-3-Migration startet mit Backout-
   Plan-getestetem Substrate (mindestens eine erfolgreiche
   Backout-Übung in Hermetic-Sandbox vor Live-Cutover).

## 4. Spec-Konsistenz-Garantie

**Wakir-Identity-Substrate-Spec v0.29.0 §5 bleibt plugin-agnostisch.**
Die Phase-3-Migration ist eine DevOps-Track-Konfigurations-
Konvergenz; sie ändert weder:

- §5.1 SPIFFE-ID-Pfad-Form,
- §5.2 Trust-Domain-URI-Format,
- §5.3 AIP-Document `issuer`-Field-Binding,
- §5.4 Cross-Trust-Domain-Federation-Bundle-Exchange,
- §5.5 Workload-API-Surface,
- §5.6 Capability-Mint-Authority pro Component-Type,
- §5.8 SPIRE-Fallback-Policy.

Lediglich §5.7 "DevOps-Track-Owner-Items" bekommt in v0.30.0 ein
zusätzliches Item ("NodeAttestor-Plugin-Wahl pro Trust-Domain")
als **Tracking-Marker**, kein Substance-Constraint.

## 5. Tracking via Roadmap

Dieses Dokument wird in `projects/roadmap.md` als Tracking-Item
referenziert; aktive Trigger-Anker werden dort in Phase-3-Sektion
sichtbar gemacht. Bei Trigger-Erfüllung wandert das Item in
`projects/roadmap-phase-3.md` als Sprint-Slot.

## 6. Open-Items für Phase-3-ADR-Vorlage (wenn Trigger erfüllt)

- [ ] CA-Auswahl-Entscheidung (separate CA vs. shared mit Federation)
- [ ] Cert-Provisioning-Pfad-Entscheidung (Image-Build vs.
      Bootstrap-Pipeline vs. TPM-sealed-secret)
- [ ] Cert-Rotation-Cadence pin (30 / 60 / 90 Tage)
- [ ] Cloud-Provider-Attestor-Pfad-Re-Evaluation (falls Pilot-Topologie
      bis Phase-3 auf Cloud migriert ist)
- [ ] Trust-Domain-übergreifender Plugin-Wahl-Konsens
      (alle Trust-Domains x509pop oder Mixed-Mode erlaubt?)

## 7. Quellen

- SPIRE NodeAttestor x509pop (Server Plugin): https://github.com/spiffe/spire/blob/main/doc/plugin_server_nodeattestor_x509pop.md — verifiziert 2026-05-15 ~22:00 CEST
- SPIRE NodeAttestor x509pop (Agent Plugin): https://github.com/spiffe/spire/blob/main/doc/plugin_agent_nodeattestor_x509pop.md — verifiziert 2026-05-15 ~22:00 CEST
- SPIFFE Configuring SPIRE (join_token scaling note): https://spiffe.io/docs/latest/deploying/configuring/ — verifiziert 2026-05-15 ~22:00 CEST
- Reza Zone-B Cross-Review 2026-05-15: `agents-workspaces/reza/outbox/2026-05-15-reza-zone-b-cross-review-kai-tag-7-bug-37.md`
- Kai Sprint-Tag-8-Done Brief 2026-05-15: PR #76 merged on `3350d2dd`

— Reza
