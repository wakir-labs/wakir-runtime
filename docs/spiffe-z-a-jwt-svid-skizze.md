# SPIFFE/SPIRE Z-A JWT-SVID Container-Identity-Skizze (Phase-2+)

- **Status:** Skizze (Phase-2-Sprint-5-Vorbereitung; Phase-3-Anker).
  Kein Implementations-Auftrag. Cross-Review-Zone-A-Vorbereitungs-
  Material.
- **Owner:** DevOps-track (Container-Orchestration / Workload-Identity-
  Substrate).
- **Cross-Review Konsument:** Wirelang-side track (Identity-Document-
  Schema; ADR-0009 Z-A-Definition).
- **Anker-ADRs:**
  - ADR-0020 §"Identity-Anker" + §"Identity-Issuer / Identity-Client"
    (SPIFFE/SPIRE als Container-Workload-Identity, Vault-1.21 SPIFFE-
    Auth, Workload-API Unix-Socket-Pattern).
  - ADR-0032 §"Zone A — Container-Identity-Substrate × Wirelang-side-
    SPIFFE-Spec" (Cross-Review-Pflicht vor Phase-1b-Container-Identity-
    Implementation; HR-track-Konsens-Protokoll).
  - ADR-0035 (Phase-1b-Bootstrap-Sprache; SPIRE bleibt Go-Native
    upstream, Adapter-Layer Python — siehe §6).
- **Authoring-Stempel:** `date -u` 2026-05-11T18:30:01Z
  (CEST 20:30, Phase-2 Sprint-4 Tag-6 60-min-Box, Box-Beginn ~20:28
  CEST, Hard-Stop 21:28 CEST).
- **Geltungsbereich:** dieses Dokument ist eine **Skizze** im Sinn
  der Sprint-3-Tag-1 Build-Host-Aktivierungs-Skizze. Es legt keine
  Implementation an, sondern sammelt:
  - Anker-Annahmen für die Z-A-Cross-Review-Session
  - SPIFFE-ID-Format-Vorschlag (offen für Wirelang-side Z-A-Spec)
  - JWT-SVID-Ausstellungs-Sequenz (SPIRE-Server-Setup, Workload-API,
    NATS-Adapter-Pfad)
  - Phase-Plan (Phase-2 minimal hermetic, Phase-3 federation-ready)
  - Test-Anker (was hermetic-testbar ist und was gated-live nötig
    braucht)

---

## TL;DR

**Was diese Skizze liefert:**

- **SPIFFE-Trust-Domain-Vorschlag:** `spiffe://wakir.local/` für
  Phase-2 Single-Node-PoC; Phase-3 `spiffe://<org-id>.wakir.dev/`
  für federation-fähige Multi-Org-Setups (V-908-Vorbereitung).
- **SPIFFE-ID-Pattern-Vorschlag:** `spiffe://<trust-domain>/agent/
  <persona-slug>/<persona-hash-short>` für Persona-Container;
  `spiffe://<trust-domain>/service/<service-name>` für Substrate-
  Komponenten (NATS, Orchestrator).
- **JWT-SVID-Ausstellungs-Pfad:** SPIRE-Server-Sidecar (Phase-2,
  single-node) → Workload-API Unix-Socket → Agent-Container fragt
  SVID an → NATS-Connection mit JWT-Auth.
- **6-Schritt-Phase-Plan:** Phase 2.1–2.6 mit klarer
  Phase-Übergangs-Gate-Bedingung.
- **Test-Substanz (Skizze-Beweis):** drei hermetic Tests im
  Skizze-Validations-Modus (siehe §7) — kein SPIRE-Server-Lauf
  nötig, validiert nur die SPIFFE-ID-Format-Konstanten und die
  Workload-API-Socket-Pfad-Konstanten.

**Push-Status dieser Skizze:** Workspace-Doku-only (analog
Sprint-3-Tag-1 Skizze). Public-Form-Push entfällt; der Skizze-File
bleibt im `wakir-runtime/docs/` aber führt keine Code-Änderung an
einem Substrat ein. Runbook-Annotation §7.8 (siehe §8) als
Sprint-Anker.

**Nicht-Ziele dieser Skizze (P2 explizit):**

- Keine SPIRE-Server-Image-Auswahl-Entscheidung (CEO-Material-
  Kosten + Wirelang-track-Cross-Review nötig).
- Keine NATS-Auth-Plugin-Final-Entscheidung (`nats-server`
  unterstützt JWT-Auth nativ, aber das Format des JWT-Claims-Sets
  ist Z-A-Cross-Review-pflichtig).
- Keine Vault-Backend-Konfiguration (V-907 + Z-A-Folge-Slot,
  Phase-3).
- Keine Phala-Cloud-TEE-Attestation-Integration (V-904 Z-D-Folge-
  Slot, Phase-3).

---

## 1. Anker-Annahmen

**A1 (verified).** SPIRE-Server ist die kanonische Workload-
Identity-Issuer-Komponente per ADR-0020 §"Identity-Issuer". SPIRE
ist Go-Native (CNCF-graduated); der DevOps-track konsumiert SPIRE als
Sidecar-Container, schreibt keinen Go-Code (ADR-0035 §"Bootstrap-
Sprache").

**A2 (verified).** Phase-1b läuft ohne SPIFFE/SPIRE auth. NATS-
Substrate ist im Phase-1b-Compose-Layout authentifizierungs-frei
(Runbook §"Security note" Z. 965–970). Z-A-Auth-Upgrade ist
explizit Sprint-3/Phase-2-Folge-Slot.

**A3 (P2 conjecture).** Cross-Review-Zone-A-Konsens hat noch nicht
stattgefunden (kein HR-track-Konsens-Protokoll für Z-A in `wakir-corp`
oder `kai/inbox/` sichtbar). Diese Skizze ist Vorbereitungs-Material
für die Z-A-Session, nicht das Resultat einer abgeschlossenen
Session. **Daher gilt:** jeder konkrete Format-Vorschlag in §3
und §4 ist **vorgeschlagen, nicht entschieden**. Wirelang-side
track owned die Identity-Document-Schema-Spec; DevOps-track owns
Container-Identity-Substrate-Implementation.

**A4 (verified).** Vault-1.21 hat native SPIFFE-Auth-Methode
(ADR-0020 §"Vault 1.21 SPIFFE-Auth seit"). Phase-3-Vault-
Konfiguration ist out-of-scope für diese Skizze; aber das SPIFFE-
ID-Format muss Vault-Auth-Methode-kompatibel bleiben (Pfad-
basiertes Matching).

**A5 (P2 conjecture).** Phase-2-Single-Node-Setup nutzt einen
**lokalen Trust-Domain-Namen** (`wakir.local`), nicht eine FQDN.
Phase-3-Federation-Setup verlangt FQDN-Trust-Domain (`<org-id>.
wakir.dev` oder analog), weil SPIFFE-Federation über DNS-resolvable
Trust-Domain-Namen läuft. Dieser Übergangspunkt ist ein expliziter
Phase-Gate, kein versteckter Substrat-Wechsel.

**A6 (verified).** Persona-Hash-Pinning V-907 (ADR-0009 CEO-Antwort
A6) ist Wirelang-track-owned Hash-Format-Spec + DevOps-track-owned
Build-Step-Implementation + Matrix-Lead-Cross-Review. Persona-Hash geht in
SPIFFE-ID-Path-Component-3 ein (siehe §3.1) — das ist der
**Identity-Bindung-Punkt** zwischen V-907-Hash und Container-
Identity. Drift zwischen Persona-Hash und SPIFFE-ID-Path führt zu
SVID-Issue-Failure (gewünschtes Verhalten).

**A7 (P2 conjecture).** SPIRE-Server-Single-Node-Compose-Setup ist
für Phase-2 ausreichend. Phase-3 (V-904-Phala-Cloud) verlangt
SPIRE-Cluster-Mode mit Datastore-Backend (SQLite oder Postgres).
Diese Skizze plant Phase-2 mit SQLite-Datastore (boring-default).

---

## 2. SPIFFE-Trust-Domain-Vorschlag

| Phase | Trust-Domain                  | Begründung                                                                                           |
| ----- | ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| 2     | `wakir.local`                 | Single-Node, kein DNS-Resolve-Risiko, kein Lock-in auf öffentliche Domain                            |
| 3a    | `<org-id>.wakir.dev`          | Federation-fähig; Wakir-Labs als Mutter-Domain; per-Org-Subdomain (V-908-Cross-Org-Vorbereitung)     |
| 3b    | `<org-id>.<custom-domain>`    | White-label-Pfad für Customer-Self-Hosting (Phase-3-Multi-Tenancy)                                   |

**Phase-Übergang 2 → 3a:** SPIRE-Server-Config-Edit + DNS-Setup +
SVID-Reissue-Pass. Keine Persona-Hash-Änderung nötig (Path-Components
2 + 3 bleiben stabil; nur Trust-Domain ändert).

**Decision-Slot:** Wirelang-side Z-A-Konsens muss bestätigen, dass
das Trust-Domain-Format kompatibel mit dem Identity-Document-
Schema-Issuer-Feld ist. Falls Z-A-Spec ein anderes Format verlangt
(z.B. `spiffe://wakir/<env>/` ohne Org-Komponente), dann ist diese
Skizze Z-A-bound zu überschreiben.

---

## 3. SPIFFE-ID-Path-Pattern-Vorschlag

### 3.1 Persona-Container-IDs

```
spiffe://<trust-domain>/agent/<persona-slug>/<persona-hash-12>
```

| Komponente            | Beispiel              | Quelle                                                                                       |
| --------------------- | --------------------- | -------------------------------------------------------------------------------------------- |
| `<trust-domain>`      | `wakir.local`         | §2                                                                                           |
| `<persona-slug>`      | `mira`, `kai`, `reza` | ADR-0032 §"Subagent-Slug"; Klar-Slug-Pattern (`mira`, `tomas`, `reza`, `kai`, `aisha`, ...)  |
| `<persona-hash-12>`   | `a3f2c1e8d4b7`        | V-907-Persona-Hash erste 12 Hex-Chars (Wirelang-track-Spec: UTF-8-NFC + LF + trailing-strip + BOM-strip + Final-Newline + `[ \t]+$`-regex; verwendetes Hash-Verfahren ist Z-A-Spec-Slot) |

**Begründung Path-Component-3 = Persona-Hash-12:**
- Drift-Detection: ein Persona-Markdown-Edit produziert einen
  neuen Hash, was eine neue SPIFFE-ID erzeugt; die alte SVID wird
  beim nächsten Workload-API-Refresh nicht mehr ausgestellt
  (gewünschtes Verhalten — V-907 Substanz).
- Multi-Persona-Deployment-Ready: zwei Container mit demselben
  `<persona-slug>` aber unterschiedlichem `<persona-hash-12>` sind
  unterscheidbar (z.B. canary-deploy einer neuen Persona-Version).
- 12 Hex-Chars (48 Bits) Kollisionsraum für Persona-Hashes
  ausreichend; Vergleich erfolgt nur innerhalb derselben
  `<persona-slug>`-Untermenge.

**Decision-Slot:** die `<persona-hash-12>`-Länge (12 vs. 16 vs. 8
Hex-Chars) ist Z-A-Cross-Review-Slot. 12 ist Skizze-Vorschlag;
Wirelang-side Identity-Document-Schema kann andere Länge verlangen.

### 3.2 Substrate-Service-IDs

```
spiffe://<trust-domain>/service/<service-name>
```

| Service                | SPIFFE-ID Beispiel                                |
| ---------------------- | ------------------------------------------------- |
| NATS-JetStream         | `spiffe://wakir.local/service/nats`               |
| Orchestrator           | `spiffe://wakir.local/service/orchestrator`       |
| SPIRE-Server (self)    | `spiffe://wakir.local/service/spire-server`       |
| Health-Check-Cron      | `spiffe://wakir.local/service/health-check-cron`  |

**Begründung Path-Component-1 = `service` (statt `agent`):**
- Klare Disambiguierung Persona-Container (`/agent/...`) vs.
  Infrastruktur-Service (`/service/...`).
- Wirelang-side Identity-Document-Schema kann pro-Component-Type
  unterschiedliche Caveat-Sets erlauben (z.B. Persona-Container
  können Capability-Tokens minten, Services können das nicht).

---

## 4. JWT-SVID-Ausstellungs-Sequenz

### 4.1 Phase-2-Single-Node-Topologie

```
┌────────────────────────────────────────────────────────────┐
│ podman-compose pod (wakir-runtime Phase-2)                 │
│                                                            │
│  ┌──────────────┐    Workload-API   ┌──────────────────┐   │
│  │ SPIRE-Server │ ◄──Unix-socket──► │ Persona-Container │   │
│  │  (sidecar)   │   /run/spire/...  │  (e.g. mira)     │   │
│  └──────┬───────┘                   └────────┬─────────┘   │
│         │                                    │             │
│         │  ▲ workload attestation             │ JWT-SVID   │
│         │  │ (process attestor: UID + EID)    │ Bearer-tok │
│         │                                    ▼             │
│         │                            ┌──────────────────┐   │
│         │                            │ NATS-JetStream   │   │
│         │                            │ (jwt auth)       │   │
│         │                            └──────────────────┘   │
│         │                                                  │
│         │ SQLite-Datastore (Phase-2)                       │
│         │ Postgres (Phase-3a)                              │
│         ▼                                                  │
│   /var/lib/spire/datastore.sqlite3                         │
└────────────────────────────────────────────────────────────┘
```

### 4.2 Sequenz-Schritte (Phase-2-Boot)

1. **SPIRE-Server-Start.** SPIRE-Server-Container startet,
   konsumiert `/etc/spire/server/server.conf`, lädt Trust-Bundle
   (Phase-2: self-signed; Phase-3: Federation-Bundle).
2. **Workload-Registry-Population.** SPIRE-Server liest
   `registration-entries.yaml` (statisch in Phase-2; in Phase-3
   per OIDC-Provider oder Persona-Attestor-Plugin).
3. **Persona-Container-Start.** Persona-Container (e.g. `mira`,
   `kai`, `reza` agent slugs) starten
   mit Workload-API-Socket-Mount (`/run/spire/sockets/agent.sock`,
   read-only).
4. **Workload-Attestation.** Persona-Container ruft Workload-API
   `FetchJWTSVID`-RPC mit `audience=nats://wakir.local`.
   SPIRE-Server attestiert via Process-Attestor (UID + Container-
   Image-Hash-Match gegen Registration-Entry).
5. **JWT-SVID-Return.** SPIRE-Server stellt JWT-SVID mit
   - `sub` = `spiffe://wakir.local/agent/mira/<persona-hash-12>`
   - `aud` = `["nats://wakir.local"]`
   - `exp` = 15 min ab Issue-Time (boring-default)
   - `iss` = `https://wakir.local/spire-server`
6. **NATS-Connection.** Persona-Container connectet zu NATS mit
   `nats.connect(url, user_jwt=<jwt>, ...)`. NATS-Server validiert
   JWT gegen SPIRE-Trust-Bundle-Public-Key.
7. **Refresh-Loop.** Persona-Container hält
   `WatchJWTSVIDs`-Stream offen; SPIRE-Server pushed neue SVID
   bevor `exp - 5 min`. Persona-Container reconnected NATS mit
   neuer SVID (NATS-2.10+ unterstützt JWT-Refresh ohne
   Connection-Drop, per `nats.io`-Roadmap-Item — P2 conjecture,
   muss in Z-A-Session verifiziert werden).

### 4.3 JWT-Claims-Set (Vorschlag)

```json
{
  "sub": "spiffe://wakir.local/agent/mira/a3f2c1e8d4b7",
  "aud": ["nats://wakir.local"],
  "iss": "https://wakir.local/spire-server",
  "exp": 1715600000,
  "iat": 1715599100,
  "jti": "<unique-svid-id>"
}
```

**Decision-Slot:** Custom-Claims (z.B. `persona-slug`, `org-id`,
`session-id`) sind Wirelang-side Z-A-Schema-Slot. Diese Skizze
plant keine Custom-Claims; falls die Identity-Document-Schema
welche verlangt, werden sie in §4.3 als SPIRE-Registration-Entry-
Extensions konfiguriert.

---

## 5. SPIRE-Server-Config-Skizze

Minimal-Phase-2-Config-Pattern (nicht Production-ready, nur Skizze):

```hcl
# /etc/spire/server/server.conf  (HCL)
server {
    bind_address = "127.0.0.1"
    bind_port    = "8081"
    socket_path  = "/run/spire/sockets/server.sock"
    trust_domain = "wakir.local"
    data_dir     = "/var/lib/spire/server"
    log_level    = "INFO"
    default_x509_svid_ttl = "1h"
    default_jwt_svid_ttl  = "15m"
}

plugins {
    DataStore "sql" {
        plugin_data {
            database_type = "sqlite3"
            connection_string = "/var/lib/spire/server/datastore.sqlite3"
        }
    }
    KeyManager "disk" {
        plugin_data {
            keys_path = "/var/lib/spire/server/keys.json"
        }
    }
    NodeAttestor "join_token" {
        plugin_data {}
    }
}
```

**Boring-default-Begründung:**
- SQLite-DataStore: keine separate DB-Engine in Phase-2 (kein
  Postgres-Container). Phase-3a-Migration-Pfad: SQLite-Dump →
  Postgres-Import (SPIRE-CLI hat dafür Tools).
- Disk-KeyManager: Phase-2 ausreichend; Phase-3 Vault-Transit-
  KeyManager (siehe ADR-0020 §"Vault 1.21 SPIFFE-Auth").
- Join-Token-NodeAttestor: Phase-2 manueller Node-Enrollment;
  Phase-3 Workload-Attestor-Plugin-Switch (z.B. K8s-PSAT-Attestor
  in K8s-Phase-3-Extension).

---

## 6. Adapter-Layer-Pfad (ADR-0035-bound)

SPIRE ist Go-Native. Der DevOps-track schreibt keinen Go-Code (ADR-0035
§"Bootstrap-Sprache"). Konsumtions-Pfad:

1. **SPIRE-Server-Container:** offizielles Image
   `ghcr.io/spiffe/spire-server` (P2 conjecture — Image-Tag-
   Konkretisierung ist Cosign-Pinning-Slot analog Tag-3 NATS-
   Image-Pin-Praxis).
2. **SPIRE-Workload-API-Client (Python):** das Python-Package
   `py-spiffe` (CNCF-spiffe-Sub-Project) hat einen Workload-API-
   Client. P2 conjecture: das Package ist maintained und
   PyPI-published. **Verifikation pflichtig in Z-A-Session.**
3. **NATS-JWT-Auth-Adapter:** `nats-py` 2.x+ unterstützt
   `user_jwt`-Connection-Parameter (P7 verified — `nats-py` README
   listet `user_jwt` als `connect()`-Argument; bei nächster
   `nats-py`-Upgrade ist die API-Stabilität zu prüfen).

**Wichtig:** kein Eigenbau von SPIRE-Server-Logik oder
Workload-API-RPC-Protokoll. Der DevOps-track konsumiert die existierende
SPIRE-Implementation als Container-Sidecar und ruft die
Workload-API per `py-spiffe`-Client. Drift gegen SPIFFE-Spec ist
SPIRE-Upstream-Concern, nicht DevOps-track-Concern.

---

## 7. Test-Anker (Skizze-Validations-Modus)

Die folgenden drei Tests sind **Skizze-internal**: sie prüfen
die SPIFFE-ID-Format-Konstanten und Workload-API-Socket-Pfad-
Konstanten, nicht eine live SPIRE-Instanz. Hermetic, kein SPIRE-
Container nötig, kein NATS-Live-Cluster nötig.

| # | Test | Was es pinnt |
|---|---|---|
| T-Tag6-Z-A-01 | `test_spiffe_id_pattern_constants_are_well_formed` | Persona-ID-Pattern matched die §3.1 Regex; Service-ID-Pattern matched §3.2 Regex; Trust-Domain-Phase-2-Konstante ist `wakir.local` |
| T-Tag6-Z-A-02 | `test_persona_hash_short_is_12_hex_chars` | Persona-Hash-12 ist 12 lower-case Hex-Chars (Decision-Slot offen für Z-A; aber wenn 12, dann formal validierbar) |
| T-Tag6-Z-A-03 | `test_workload_api_socket_path_is_documented_phase_2_default` | `/run/spire/sockets/agent.sock` als Phase-2-Default ist als Konstante definiert; Phase-3a-Default ist überschreibbar via Env-Var |

Diese Tests landen in `tests/orchestrator/test_spiffe_z_a_skizze.py`.
Sie konsumieren ein neues Modul `orchestrator.spiffe_skizze`
das die Konstanten als Python-Konstanten exportiert (kein
Implementation-Code; nur die Format-Vorschläge als testbare
Konstanten).

**Zweck der Tests:** wenn die Skizze nachträglich editiert wird
(Z-A-Konsens setzt anderes Trust-Domain-Format oder andere Hash-
Länge), brechen die Tests sichtbar und das Konstanten-Modul muss
mit-editiert werden. Das ist die Drift-Detection-Disziplin für
einen Skizze-Pfad.

---

## 8. Runbook-Anker §7.8

Diese Skizze wird im Runbook unter §7.8 als Sprint-Anker
registriert:

> §7.8 SPIFFE/SPIRE Z-A JWT-SVID Container-Identity-Skizze
> (Phase-2 Sprint-4 Tag-6, docs/spiffe-z-a-jwt-svid-skizze.md).
> Cross-Review-Zone-A-Vorbereitungs-Material. Keine Substrate-
> Änderung; reine Doku-Skizze plus 3 hermetic Format-Konstanten-
> Tests. Z-A-Konsens-Trigger erforderlich bevor Phase-2-Sprint-5
> Workload-API-Adapter-Implementation startet.

Die §7.8-Sektion im Runbook-Body führt die Skizze als
"siehe docs/spiffe-z-a-jwt-svid-skizze.md" mit Bucket-summary
auf, ähnlich wie §7.4 das Tag-2-First-Time-Live-Smoke-Execution-
Record führt.

---

## 9. Sprint-5-Vorbereitung (Phase-Plan)

Phase-2-Sprint-5 ist der **frühestmögliche** Sprint für Z-A-
Implementation. Bedingung: Z-A-Konsens-Marker abgeschlossen
(HR-track Cross-Review-Protokoll); ohne Konsens kein Sprint-5-Z-A-Item.

**Phase-2.1 (Sprint-5 Tag-1):** SPIRE-Server-Container als Sidecar
zum NATS-Substrate addieren. Compose-Erweiterung
`compose/spire.yaml`. Hermetic Test: SPIRE-Server-Container starts.

**Phase-2.2 (Sprint-5 Tag-2):** Workload-API-Client-Setup in
Persona-Container-Base-Image (`py-spiffe`-Dependency).
Hermetic Test: Workload-API-Client-Module imports without error.

**Phase-2.3 (Sprint-5 Tag-3):** SVID-Fetch-Smoke-Test. Live-gated
(`WAKIR_SPIRE_LIVE=1`): start SPIRE-Server + register a test
workload, fetch JWT-SVID, validate JWT-claims.

**Phase-2.4 (Sprint-5 Tag-4):** NATS-JWT-Auth-Integration.
NATS-Server-Config switchen auf JWT-Auth-Mode mit SPIRE-Trust-
Bundle. Hermetic Test: NATS-Server-Config-File parsing.

**Phase-2.5 (Sprint-5 Tag-5):** End-to-End-Smoke. Live-gated
(`WAKIR_SPIRE_LIVE=1` AND `WAKIR_NATS_LIVE=1`): persona-container
fetcht JWT-SVID, connectet NATS mit JWT, schreibt + liest ein
KV-Bucket-Entry. Cross-Review-Memo Z-A an Wirelang-side track
(Konsumtions-Schnittstelle).

**Phase-2.6 (Sprint-5 Tag-6):** Runbook-§7.8-Erweiterung mit
Production-Operations-Substanz (Token-TTL-Recovery,
SPIRE-Server-Restart-Behavior, NATS-Reconnect-on-SVID-Refresh).
Acceptance-Doku-Konsolidat für die CEO.

**Phase-3-Trigger (Cross-Review-Zone-D-bound):** Phala-Cloud-TEE-
Attestation-Integration ist Phase-3 V-904. Diese Skizze ist Z-D-
neutral; das SPIFFE-ID-Pattern in §3.1/§3.2 ist TEE-Attestation-
kompatibel weil Persona-Hash und Service-Name beide
TEE-Attestor-Plugin-konsumierbar sind.

---

## 10. Risiken und Decision-Slots (P2 conjecture)

| Risiko / Slot | Disposition |
| --- | --- |
| Z-A-Konsens-Marker noch nicht abgeschlossen | Skizze ist Vorbereitungs-Material; kein Phase-2-Sprint-5-Z-A-Implementation-Start ohne Konsens |
| Trust-Domain-Format-Vorschlag (`wakir.local` Phase-2) ist nicht authoritative | Z-A-Schema-Spec kann anderes Format verlangen; Skizze ist Z-A-bound überschreibbar |
| Persona-Hash-Pfad-Länge (12 Hex) ist Skizze-Vorschlag | Wirelang-side Identity-Document-Schema kann andere Länge fordern (8, 16, 32) — formales Z-A-Slot |
| `py-spiffe`-Paket-Maintenance-Status nicht verifiziert | Z-A-Session-Pflicht: PyPI-Status + Maintainer-Aktivität + License-Check vor Sprint-5-Tag-2-Implementation |
| NATS-2.10+-JWT-Refresh-on-Reconnect-Verhalten P2 | Z-A-Session-Pflicht: Roadmap-Item-Status verifizieren oder Workaround dokumentieren |
| Phase-3-Trust-Domain-FQDN-Migration | Kein Substrat-Wechsel, aber SVID-Reissue-Pass nötig; Phase-Plan §9 listet das nicht — Folge-Skizze in Phase-3 |
| V-907-Persona-Hash-Format-Drift | Wirelang-track-Owner-Hash-Format-Spec gilt; falls die Spec sich noch ändert, ist Path-Component-3 dieser Skizze automatisch bound |
| Vault-Backend-Integration | Z-A-Folge-Slot; nicht Sprint-5-Phase-2-Scope; ADR-0020 hat Pfad benannt aber nicht spezifiziert |

---

## 11. Anti-Bullshit-Disziplin (P5/P7)

- **Authoring-Zeitstempel:** `date -u` 2026-05-11T18:30:01Z
  (CEST 20:30, Phase-2 Sprint-4 Tag-6).
- **Runbook-Z-A-Referenzen verified:** Zeilen 704, 966, 1161,
  1352, 1527, 1659 in `docs/orchestrator-nats-kv-phase-1-runbook.md`
  (Tag-5-Branch-Stand, commit `7fc13ee`).
- **ADR-0020-Z-A-Referenzen verified:** Zeilen 292, 322, 356,
  375–376, 385–386, 438, 450, 553, 579 in
  `decisions/0020-container-orchestrator-architektur.md`
  (`grep -n` Aufruf gegen die Datei).
- **ADR-0032-Z-A-Definition verified:** Persona-Datei
  `/var/home/fred/AI-Corp/.claude/agents/kai.md` §2 "Cross-Review-
  Zonen A-D" beschreibt Zone A als "Container-Identity-Substrate ×
  Wirelang-side-SPIFFE-Spec" mit HR-track-Konsens-Protokoll-Pflicht.
- **Stash-Disposition (Tag-5-Outbox §9 Vorschlag):** Stash `tag-4-
  federation-routes-prior-attempt` Tag-6-droppd (siehe Tag-6-Outbox
  §"Stash-Drop-Status"). Verified via `git stash drop stash@{0}`
  → `Dropped stash@{0} (fa598a48...)`; post-drop `git stash list`
  ist leer.

**P2 Vermutungs-Kennzeichnungen:**

- A3, A5, A7 sind explizit P2 markiert (Z-A-Konsens-Status,
  Trust-Domain-FQDN-Annahme, SPIRE-Single-Node-Phase-2-Ausreichend-
  Annahme).
- `py-spiffe`-PyPI-Status, NATS-JWT-Refresh-Verhalten, SPIRE-Image-
  Tag-Konkretisierung sind alle P2 in §10 dokumentiert.
- Custom-Claims-Schema-Slot ist explizit Wirelang-side-Decision.

---

## 12. Domain-Disziplin

- **DevOps-track-Owned-Substanz:** Container-Identity-Substrate-Pfad, SPIRE-
  Server-Config-Skizze, Workload-API-Sequenz, NATS-JWT-Auth-Adapter-
  Pfad, Phase-Plan, Runbook-§7.8-Anker, hermetic Format-Konstanten-
  Tests.
- **Wirelang-Side-Owned (Cross-Review-Zone-A):** Identity-Document-
  Schema, SPIFFE-ID-Pfad-Component-Längen-Decision, Custom-Claims-
  Set, Trust-Domain-Format-Final-Decision.
- **Wirelang-track-Owned (V-907 Hash-Format-Spec):** Persona-Hash-Verfahren
  (Hash-Algorithmus + Input-Normalisierung); diese Skizze
  konsumiert das Resultat als Hex-Hash-String und schneidet die
  ersten 12 Chars ab — kein Hash-Algorithmus-Eingriff.
- **Matrix-Lead-Cross-Review (V-907 in WAT-Leaf-Hash-Eingabe):** kein
  Skizze-Eingriff; V-907 als `personapin` L1-CloudEvents-Extension
  ist separate Sub-Spec.
- **Kein ADR:** dies ist Skizze, keine Architektur-Entscheidung.
  Sprint-5-Phase-2-Z-A-Implementation kann ohne neuen ADR starten
  nach Z-A-Konsens-Protokoll (analog Z-B-Konsens-Pattern Sprint-2
  Tag-7).
