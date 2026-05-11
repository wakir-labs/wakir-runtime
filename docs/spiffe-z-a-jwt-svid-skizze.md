# SPIFFE/SPIRE Z-A JWT-SVID Container-Identity-Skizze (Phase-2+)

- **Status:** Skizze, Re-Write-Pass Sprint-6-Tag-5 nach Reza-Z-A-
  Ack 2026-05-11T21:16Z. Vier Z-A-Slots beantwortet
  (Ack/Ack/Ack-with-correction/Ack-with-hard-correction); Aisha-
  Konsens-Marker-Recording pending. Skizze ist nicht mehr reines
  Vorbereitungs-Material — die Refinement-/Korrektur-Items sind
  eingearbeitet. Phase-2-Sprint-5-Z-A-Implementations-Start nach
  Aisha-Marker.
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

- **SPIFFE-Trust-Domain (Z-A-Ack-Stand Sprint-6-Tag-5):**
  `spiffe://wakir.local/` für Phase-2 Single-Node-PoC; Phase-3a
  `spiffe://<FTD-ID>.wakir.dev/` für federation-fähige Multi-Org-
  Setups (V-908-Vorbereitung; `<FTD-ID>` ist V-908-Federation-
  Pattern, NICHT freie Customer-Subdomain). Phase-3b White-Label
  deferred.
- **SPIFFE-ID-Pattern (Z-A-Ack-Stand):** `spiffe://<trust-domain>/
  agent/<persona-slug>/<persona-hash-12>` für Persona-Container;
  `spiffe://<trust-domain>/service/<service-name>` für Substrate-
  Komponenten. V-907-Hash full-form `sha256:<64-hex>` bleibt
  audit-anker; 12-Hex-Char-Component-3 ist Display-Slice (hash-
  algorithm-agnostic).
- **JWT-SVID-Ausstellungs-Pfad:** SPIRE-Server-Sidecar (Phase-2,
  single-node) → Workload-API Unix-Socket → Persona-Container holt
  SVID per Wirelang-side Adapter-Layer
  (`wirelang/adapters/spiffe_workload_api.py`) → NATS-Connection
  via `nats-py` `user_jwt_cb`-Callback-Pattern (Client-Side-
  Refresh-on-Reconnect, kein NATS-Server-Feature).
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

**A3 (Sprint-6-Tag-5 upgraded — Z-A-Konsens vier Slots
beantwortet).** Cross-Review-Zone-A: Reza-Ack 2026-05-11T21:16Z
hat die vier offenen Slots adressiert (Trust-Domain-Format, SPIFFE-
ID-Path-Pattern, `spiffe`-Package-Maintenance, NATS-JWT-Refresh).
Aisha-Konsens-Marker-Recording-Step ist Operations-pending. Diese
Skizze enthält die Re-Write-Items aus der Reza-Ack-Counter-Spalte:
PyPI-Naming-Correction (`spiffe`), `user_jwt_cb`-Callback-Pattern,
FTD-ID-Pattern-Refinement, Adapter-Layer-Indirection-Constraint.
**Daher gilt Sprint-6-Tag-5:** Format-Vorschläge in §3, §4 sind
mit Refinements ratifiziert (Reza-Ack-Slot-1+2); Implementation-
Slots in §9 sind Aisha-Marker-bound. Wirelang-side owned die
Identity-Document-Schema-Spec; DevOps-track owned Container-
Identity-Substrate-Implementation.

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
| 3a    | `<FTD-ID>.wakir.dev`          | Federation-fähig; Wakir-Labs als Mutter-Domain; per-Org-Subdomain (V-908-Cross-Org-Vorbereitung). `<FTD-ID>` ist V-908-Term-of-Art (Federated-Trust-Domain-Identifier) — siehe Refinement unten     |
| 3b    | deferred                      | White-Label-Pfad für Customer-Self-Hosting (Phase-3-Multi-Tenancy); Reza-Ack-Slot-1 §1.4 deferred Phase-3-Reopen-Slot, kein Phase-2/3a-Konsens-Scope     |

**Phase-Übergang 2 → 3a:** SPIRE-Server-Config-Edit + DNS-Setup +
SVID-Reissue-Pass. Keine Persona-Hash-Änderung nötig (Path-Components
2 + 3 bleiben stabil; nur Trust-Domain ändert).

**Refinement Sprint-6-Tag-5 (Reza-Ack-Slot-1):**
`<FTD-ID>` ist **literal Federated-Trust-Domain-Identifier**
(V-908-Federation-Spec-Pattern, NICHT freie Customer-Subdomain).
FTD-ID-Constraints (Wirelang-side V-908-spec gem. Reza-Ack §1.3):

- Slug-Form: `[a-z][a-z0-9-]{2,30}` (lower-case, kein
  DNS-special-char in der Slug-Komponente, kein dot/underscore)
- Registriert in der Federation-Routes-NATS-KV-Bucket
  `wakir-federation-routes` (Phase-1b-Sprint-2-Substanz, DevOps-
  track + Wirelang-side gemeinsam)

**Phase-3a-Migration-Gate:** FTD-ID-Pattern muss eingehalten sein
bevor `<FTD-ID>.wakir.dev`-Trust-Domain in SPIRE-Server-Config-
Render-Step gezogen wird. SPIRE-Config Phase-2 muss noch nichts
daran ändern (Trust-Domain ist `wakir.local`), aber der Phase-3a-
Migration-Plan in §9 muss FTD-ID-Pattern-Validation als
Pre-Migration-Step haben.

**Z-A-Status Sprint-6-Tag-5:** Trust-Domain-Format `wakir.local`
(Phase-2) + `<FTD-ID>.wakir.dev` (Phase-3a) ist Identity-Document-
Schema-`issuer`-URI-kompatibel (Reza-Ack §1.2). Phase-3b ist
deferred bis Phase-3-Reopen-Session.

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

**Z-A-Konsens-Hard-Pin Sprint-6-Tag-5 (Reza-Ack-Slot-2 §2.2-§2.3):**

- V-907-Persona-Hash full-form ist **immer**
  `sha256:<64-lower-case-hex>` (RFC-8785 JCS + sha256, P7-verified
  Reza-Ack `pengine/wakir-runtime/wirelang/specs/persona-hash-spec.md`
  §3). Das ist der einzige byte-stabile Hash-Audit-Anker und der
  WAT-Leaf-Input (Matrix-Lead-Domain).
- SPIFFE-ID-Path-Component-3 ist ein **12-Hex-Char-Display-Slice**:
  `sha256_hex(JCS(canonical_subset))[:12]` (12-Char-Prefix des hex-
  Output ohne `sha256:`-Präfix). Beispiel: full-hash
  `sha256:a3f2c1e8d4b7...64-hex...` → SPIFFE-ID-Component
  `a3f2c1e8d4b7`. Kein Hash-Format-Variant, nur Display-Slice.
- Kein Drift zwischen V-907-Hash und SPIFFE-ID: beide leiten sich
  aus demselben byte-stabilen JCS-canonical-subset her.
- **Hash-Algorithm-Agnostic:** falls V-907 in Phase-3 zu blake3
  oder sha3 migriert wird, bleibt das 12-Hex-Char-Prefix-Pattern
  stabil — die SPIFFE-ID-Format-Konstante muss nicht geändert
  werden (Z-A-Konsens-Fixpunkt Reza-Ack §2.3).

**12-Hex-Char-Akzeptanz (Reza-Ack §2.3):**

- Kollisionsraum 2^48 = 2.8 × 10^14 — für ≤10^6 Persona-Versions
  pro `<slug>`-Untermenge Birthday-Bound < 10^-3.
- Industrie-Range: Git-Short-SHA 7 Hex (28 Bits), Docker-Image-
  Short-Tag 12 Hex (48 Bits).
- Display-Friendly (12 Chars lesbar in einer Zeile).

**Cross-Reference WAT-Leaf-Hash (Matrix-Lead-Owner Tomás):** WAT-
Leaf-Hash konsumiert die full-form `sha256:<64-hex>`; SPIFFE-ID
konsumiert das 12-Char-Slice. Disjunkt, keine Z-A-Touch.

**Persona-vs-Service-Disambiguation auf Component-1 (Reza-Ack
§2.4):** `/agent/` darf Capability-Tokens **minten** (Wirelang-
side Identity-Document-Schema-Constraint, Issuer-Role per AIP-
Document); `/service/` darf Capability-Tokens **konsumieren** aber
NICHT minten. Diese Constraint ist Wirelang-side-owned, kein
DevOps-track-Slot — aber relevant für SPIRE-Registration-Entry-
Generation (Phase-3-Folge-Skizze, siehe §10 Risiko-Tabelle).

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
   `nats.connect(url, user_jwt_cb=<callable returning JWT bytes>,
   ...)`. NATS-Server validiert das im CONNECT-Frame eingebettete
   JWT gegen SPIRE-Trust-Bundle-Public-Key. Der Callback liest die
   zuletzt von `WatchJWTSVIDs` gepushte SVID — kein statisches
   `user_jwt`-String-Argument (siehe §6 §3 für Adapter-Pfad).
7. **Refresh-Loop (Client-Side-Callback-Pattern).** Persona-
   Container hält `WatchJWTSVIDs`-Stream zum SPIRE-Server für
   Background-Refresh; SPIRE-Server pushed neue SVID vor
   `exp - 5 min`. Der `nats-py`-Client wurde mit `user_jwt_cb=
   <callable>` initialisiert; das Callback liest die zuletzt
   gepushte JWT-SVID. Bei NATS-Reconnect (Network-Glitch oder
   periodischer Server-Restart) ruft `nats-py` das Callback
   automatisch auf und sendet die aktuelle SVID im neuen
   CONNECT-Frame. NATS-Server validiert das neue JWT gegen
   Trust-Bundle-Public-Key. Solange eine NATS-Connection lebt
   bleibt sie unter dem aktuellen Token gültig bis Token-`exp`.
   **Kein expliziter `connection.close() + connection.connect()`
   durch Persona-Container nötig — `nats-py` Reconnect-Mechanik
   plus Callback-Closure leisten den Refresh.**
   P7-verified: `nats/aio/client.py` Zeilen 110, 315–317, 370,
   1666–1668 (Reza-Z-A-Ack 2026-05-11T21:16Z, Skizze §11).
   **Korrektur Sprint-6-Tag-5:** ältere Skizze-Version sprach von
   "NATS-2.10+-Roadmap-Feature" — das ist falsch; Refresh-on-
   Reconnect ist Client-Side-Callback, kein Server-Feature.

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
2. **SPIRE-Workload-API-Client (Python):** das PyPI-Package
   `spiffe` (CNCF SPIFFE-Sub-Project, GitHub-Repo
   `HewlettPackard/py-spiffe`, Apache-2.0) liefert den Workload-
   API-Client und SVID-Management.
   **PyPI-Naming-Correction Sprint-6-Tag-5:** dependency-line
   ist `spiffe>=<min-version>`, NICHT `py-spiffe>=<min-version>`.
   Der GitHub-Repo-Name `py-spiffe` ist nicht der pip-install-Name.
   P7-verified (Reza-Z-A-Ack 2026-05-11T21:16Z): latest release
   `spiffe-tls v0.3.2` 2026-05-11, Apache-2.0, active maintenance,
   19 total releases, 0 open issues + 0 open PRs.
   **Wirelang-side-Constraint (Reza-Counter-Vorschlag Z-A-Slot-3):**
   kein Direkt-Import von `spiffe.workload_api` in Persona-
   Container-Code. Stattdessen ein Adapter-Modul
   `wirelang/adapters/spiffe_workload_api.py` (Wirelang-side
   Surface-Owner, siehe Reza-Sprint-6-Tag-5/6-Folge-Skizze) als
   Indirection-Layer mit eigener Surface (z.B.
   `fetch_jwt_svid(audience: str) -> JwtSvid`). Begründung:
   Library-Drift (Breaking-API-Change in `spiffe` oder
   Maintenance-Drop) bleibt Wirelang-side-Surface-stabil, ohne
   Persona-Container-Code-Mass-Edits. Adapter-Layer eröffnet
   zusätzlich einen AIP-Document-Validation-Hook beim SVID-Fetch
   (Wirelang-side Capability-Layer-Slot).
3. **NATS-JWT-Auth-Adapter (Client-Side-Callback-Pattern).**
   `nats-py` 2.x+ unterstützt **`user_jwt_cb=<callable returning
   JWT bytes>`** als `connect()`-Parameter — Callback-Pattern, nicht
   statisches `user_jwt`-String-Argument. P7-verified Sprint-6-
   Tag-5 (Reza-Z-A-Ack): `nats/aio/client.py` Zeile 110 deklariert
   `JWTCallback = Callable[[], Union[bytearray, bytes]]`; Zeile
   315–317 + 370 binden das Callback an `_user_jwt_cb`; Zeile
   1666–1668 ruft das Callback **bei jedem CONNECT-Frame-Build**
   auf (also auch bei Reconnect). Konsequenz für den Adapter-
   Pfad: das Callback bezieht die zuletzt von `WatchJWTSVIDs`
   gepushte JWT-SVID aus einem Background-Refresh-Stream-Holder
   (z.B. eine `wirelang.adapters.spiffe_workload_api.JwtSvidCache`-
   Surface). Bei NATS-Reconnect wird die aktuelle SVID automatisch
   eingebettet — kein Force-Reconnect durch Persona-Container nötig.
   **Korrektur Sprint-6-Tag-5:** ältere Skizze-Version sprach von
   `user_jwt`-Connection-Parameter (statisches String-Argument);
   das ist `nats-py`-API-falsch. Der korrekte Parameter ist
   `user_jwt_cb`-Callback.

**Wichtig:** kein Eigenbau von SPIRE-Server-Logik oder
Workload-API-RPC-Protokoll. Der DevOps-track konsumiert die existierende
SPIRE-Implementation als Container-Sidecar und ruft die
Workload-API per `spiffe`-Package indirekt über den
Wirelang-side Adapter-Layer (`wirelang/adapters/spiffe_workload_api.py`).
Drift gegen SPIFFE-Spec ist SPIRE-Upstream-Concern, nicht DevOps-
track-Concern; Drift gegen `spiffe`-Library ist Wirelang-side
Adapter-Layer-Concern, nicht Persona-Container-Concern.

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
> (Phase-2 Sprint-4 Tag-6 Origin + Sprint-6-Tag-5 Re-Write nach
> Reza-Z-A-Ack 2026-05-11T21:16Z, docs/spiffe-z-a-jwt-svid-skizze.md).
> Cross-Review-Zone-A-Konsens vier Slots beantwortet (Aisha-Marker-
> Recording pending). Keine Substrate-Änderung; reine Doku-Skizze
> plus 3 hermetic Format-Konstanten-Tests. Phase-2-Sprint-5/6
> Workload-API-Adapter-Implementation entblockt nach Aisha-Marker.

Die §7.8-Sektion im Runbook-Body führt die Skizze als
"siehe docs/spiffe-z-a-jwt-svid-skizze.md" mit Bucket-summary
auf, ähnlich wie §7.4 das Tag-2-First-Time-Live-Smoke-Execution-
Record führt.

---

## 9. Phase-2 Sprint-5-Vorbereitung (Phase-Plan)

Phase-2-Sprint-5/6 ist der **frühestmögliche** Sprint für Z-A-
Implementation. Bedingung: Z-A-Konsens-Marker abgeschlossen
(HR-track Cross-Review-Protokoll, Aisha-Marker-Recording-Step
Sprint-6-Tag-5 pending nach Reza-Ack 2026-05-11T21:16Z); ohne
Marker-Stamp kein Implementation-Start.

**Sprint-6-Tag-5-Refinement:** wegen Sprint-5-Re-Prioritization
(Quadlet/cosign/capability-policies) sind die Phase-2.x-Slots als
Sprint-6/7-Items abrufbar. Phase-Marker `Sprint-5` in den
folgenden Unter-Punkten ist historisch; effektiver Start-Slot ist
Aisha-Marker-bound.

**Phase-2.1 (Sprint-6 Tag-6, DONE):** SPIRE-Server-Container als
Sidecar zum NATS-Substrate addieren. Compose-Erweiterung
`compose/spire.yaml` + Mock/Stub-Config `config/spire-server.conf`
(hermetic-only Trust-Domain `example.test` per RFC 6761 §6.5).
Hermetic Test: 16 Acceptance-Tests in
`tests/orchestrator/test_compose_spire.py` (compose-parse,
image-form, trust-domain-Hermetic-Marker, bind-mount-Pfade,
named-Volumes-Coexistenz, Hardening-Defaults, Health-Probe-Shape,
NATS-Substrate-Coexistenz-Invariant via gemeinsamer
`wakir-orchestrator`-Bridge, HCL-Config-Plugin-Pins). Image-Pin:
`ghcr.io/spiffe/spire-server:1.14.6` (tag-only; Digest-Pin
ist Cross-Review-Zone-C Cosign-Skizze-Folge-Slot pro
Sprint-6-Tag-3-Konsolidat-Sweep). Phase-2.1 ist hermetic only —
keine echten Registrations, kein SVID-Lauf, kein Host-podman-
Socket (per Mira-Direktive Sprint-6-Tag-6).

**Phase-2.2 (Sprint-5 Tag-2):** Workload-API-Client-Setup in
Persona-Container-Base-Image (PyPI-Package `spiffe`-Dependency,
konsumiert über Wirelang-side Adapter-Layer
`wirelang/adapters/spiffe_workload_api.py` — siehe §6 §2).
Hermetic Test: Adapter-Layer-Module imports without error.

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
| Z-A-Konsens-Marker recorded with refinements 2026-05-11 (Reza-Ack) | Sprint-6-Tag-5 Status: vier Slots beantwortet (Ack/Ack/Ack-with-correction/Ack-with-hard-correction). Aisha-Marker-Recording pending (Konsens-Stamp); Refinement-Items in §5 dieser Skizze + Reza-Ack §5 dokumentiert |
| Trust-Domain-Format `wakir.local` (Phase-2) + `<FTD-ID>.wakir.dev` (Phase-3a) | Ack mit Refinement Reza-Ack-Slot-1: `<org-id>` in §2 ist literal FTD-ID (V-908-Federation-Pattern, Slug-Form `[a-z][a-z0-9-]{2,30}`, registriert in `wakir-federation-routes`-Bucket). Phase-3b White-Label-Pfad ist deferred (kein Z-A-Slot in Phase-2/3a-Scope) |
| Persona-Hash-Pfad-Länge (12 Hex) | Ack mit Hard-Pin Reza-Ack-Slot-2: V-907-Hash full-form bleibt `sha256:<64-hex>` (audit-anker, WAT-Leaf-Input); SPIFFE-ID-Component-3 ist 12-Hex-Char-Prefix-Display (hash-algorithm-agnostic, stabil bei Phase-3-Hash-Algorithm-Migration zu blake3/sha3) |
| `spiffe`-Paket (PyPI) Maintenance-Status | Ack mit Correction Reza-Ack-Slot-3 (P2→P7-Upgrade 2026-05-11T21:16Z): GitHub `HewlettPackard/py-spiffe`, PyPI-Package `spiffe`, Apache-2.0, latest release `spiffe-tls v0.3.2` 2026-05-11, 19 releases, 0 open issues+PRs. **PyPI-Naming-Correction:** `spiffe`, NICHT `py-spiffe`. Wirelang-side Adapter-Layer-Constraint: kein Direkt-Import in Persona-Container-Code |
| NATS-JWT-Refresh-on-Reconnect-Verhalten | Ack mit Hard-Correction Reza-Ack-Slot-4 (P2→P7-Upgrade): `nats-py` `user_jwt_cb`-Callback-Pattern (`nats/aio/client.py` Z. 1666–1668), NICHT NATS-Server-2.10+-Feature. Refresh-on-Reconnect ist Client-Side-Callback-Pattern; das Callback wird bei jedem CONNECT-Frame-Build aufgerufen |
| Trust-Bundle-Rotation-Sequence | Phase-2-Sprint-5-Tag-6 Operator-Runbook §7.8-Erweiterungs-Item (NATS-Config-Reload + Trust-Bundle-Watch); DevOps-track-Operations, kein Wirelang-side-Block (Reza-Ack-Slot-4 §4.4) |
| Phase-3-Trust-Domain-FQDN-Migration | Kein Substrat-Wechsel, aber SVID-Reissue-Pass nötig; Phase-Plan §9 listet das nicht — Folge-Skizze in Phase-3 |
| V-907-Persona-Hash-Format-Drift | Wirelang-track-Owner-Hash-Format-Spec gilt; SPIFFE-ID-Component-3-Pattern bleibt hash-algorithm-agnostic stabil (Reza-Ack-Slot-2 Z-A-Konsens-Fixpunkt) |
| AIP-Document-zu-SPIRE-Registration-Entry-Generator | Phase-3-Folge-Skizze-Slot (nicht Sprint-5/6-Scope, Reza-Ack-Slot-2 §2.5); Cross-Track-Owner: AIP-Document-Schema Wirelang-side, SPIRE-Registration-Entry-Generation DevOps-track, Drift-Risk-Surface |
| `spiffe`-Library-Maintenance-Drop (mittelfristig) | Z-A-Folge-Slot Phase-3-Reopen (Reza-Ack-Slot-3 §3.5); Indikator: kein Release > 12 Monate, > 5 open security-issues. Adapter-Layer-Indirection isoliert Persona-Container-Code von Library-Wechsel |
| Vault-Backend-Integration | Z-A-Folge-Slot; nicht Sprint-5-Phase-2-Scope; ADR-0020 hat Pfad benannt aber nicht spezifiziert |

---

## 11. Anti-Bullshit-Disziplin (P5/P7)

- **Authoring-Zeitstempel:** `date -u` 2026-05-11T18:30:01Z
  (CEST 20:30, Phase-2 Sprint-4 Tag-6).
- **Re-Write-Zeitstempel Sprint-6-Tag-5:** `date -u`
  2026-05-11T21:35:08Z (CEST 23:35, Re-Write nach Reza-Z-A-Ack
  2026-05-11T21:16Z).
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
- **Reza-Z-A-Ack-Anker (P7-upgrades Sprint-6-Tag-5):** File
  `reza/outbox/2026-05-11-z-a-cross-review-ack.md` Zeilen 18–22
  (TL;DR-Tabelle aller vier Slot-Positionen), §3.2 (PyPI-Package-
  Name-Correction `spiffe`), §4.2 (NATS-JWT `user_jwt_cb`-Callback-
  Pattern), §5 (DevOps-track-Edit-Items für diese Skizze). Read via
  Read-tool 2026-05-11T21:35:08Z.
- **`nats-py` `user_jwt_cb`-Pattern verified durch Reza:**
  `kai/wakir-runtime/.venv/lib/python3.14/site-packages/nats/aio/
  client.py` Zeilen 110 (JWTCallback-Typdef), 315–317 (Field-
  Binding), 370 (connect-signature), 1666–1668 (CONNECT-Frame-
  Builder Callback-Invocation). Sprint-6-Tag-5 P7-Übernahme.
- **`spiffe` PyPI-Package-Name verified durch Reza:** WebFetch
  `https://github.com/HewlettPackard/py-spiffe` 2026-05-11T21:16Z.
  PyPI-Packages `spiffe` (core) + `spiffe-tls` (experimental).
  Repo-Name `py-spiffe` ist NICHT pip-install-Name.

**P2 Vermutungs-Kennzeichnungen (Sprint-6-Tag-5 reduziert):**

- A3, A5, A7 bleiben P2 markiert (Trust-Domain-FQDN-Annahme,
  SPIRE-Single-Node-Phase-2-Ausreichend-Annahme).
  **Re-Klassifikation:** A3 (Z-A-Konsens-Status) ist Sprint-6-Tag-5
  nicht mehr P2 — Konsens vier Slots beantwortet (Reza-Ack); Aisha-
  Marker-Recording-Step ist Operations-pending, nicht Skizze-
  Substanz-P2.
- **P2→P7-upgraded Sprint-6-Tag-5 (Reza-Ack):**
  - `spiffe`-PyPI-Status (active maintenance 2026-05-11, verified).
  - NATS-JWT-Refresh-Verhalten (`user_jwt_cb`-Callback-Pattern,
    Client-Side, verified `nats/aio/client.py` Z. 1666–1668).
- **P2 verbleibend:**
  - SPIRE-Image-Tag-Konkretisierung (Cosign-Pinning-Slot Phase-2-
    Sprint-5-Tag-1-Folge-Item).
  - Custom-Claims-Schema-Slot ist Wirelang-side-Decision.
  - Python-Version-Range für `spiffe`-Package (Reza-Ack §7 P2-
    Note: vermutlich 3.9+; Direct-PyPI-Metadata-Read Sprint-5-Tag-2-
    Vorbereitungs-Item).
  - FTD-ID-Slug-Pattern-Konstanten `[a-z][a-z0-9-]{2,30}` basieren
    auf V-908-Spec-Annahme (Reza-Ack §7 P2-Note); Re-read der V-908-
    Spec ist Z-A-Folge-Slot.

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
