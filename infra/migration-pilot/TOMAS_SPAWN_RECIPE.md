<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Tomás-Persona-Spawn-Recipe — ADR-0058 Pilot-Phase Schritt 9 (Operator-Hand)

**Status:** Phase-1c ADR-0058-Pilot, Sprint-9 Tag-9 (Migrations-Pilot
Schritt 9, Spawn-Procedure-Spec). Operator-Hand-Pfad für den Aufsichtsrat
(Fred). Sandbox-Boundary: dieses Dokument beschreibt was der Operator
auf der Pilot-VM tut; die Sandbox führt **keinen Live-Spawn** aus
([`feedback_sandbox_host_trennung.md`](../../docs/feedback-anchors.md)).

**Companion-Artefakte:**

- `wirelang-rust/crates/persona-pilot-export/` — Schritt-8-CLI
  `wakir-persona-pilot-export` (produziert das Export-Bundle).
- `infra/spire/federation/PROXMOX_BRING_UP_RECIPE.md` — Voraussetzung
  Schritt 1 (Phase-1b Live-Bring-up auf Proxmox-VM).
- `docs/migration-pilot-validation-phase-setup.md` — Schritt 10
  (Pilot-Validation-Phase mit Acceptance-Kriterien + Observability +
  Rollback-Trigger).
- `docs/migration-playbook.md` (AI-Corp Hauptrepo) — Sequenz-Anker.

**Lesepfad:** dieser Recipe-Text ist **sequenziell**. Jeder Schritt
schliesst mit einer Verifikation; jede Verifikation hat einen erwarteten
Output. Bei einem Mismatch: VM-Snapshot zurueckrollen (§7), nicht
weiterklicken.

## 0. Was hier passiert (Überblick)

Wir spawnen die **Tomás-Persona** auf der Pilot-VM (Phase-1b-Bring-up,
ADR-0055-Stufe-3-Proxmox-Pattern). Der Spawn nutzt:

- den **Export-Bundle** aus Schritt 8 (von der Operator-Sandbox
  per `scp` transferiert),
- eine **SPIFFE-SVID** vom Pilot-VM-SPIRE-Server (Trust-Domain
  `wakir.test`, Workload-Identity `spiffe://wakir.test/persona/tomas`),
- den **NATS-KV-Bucket** `wakir-persona-state-tomas`
  (Sprint-Pengine-7-Tag-4-Spec §3.4 + §3.7.5 PersonaStateBacking),
- eine **Quadlet-Unit** `wakir-persona-tomas.service` (Sprint-9-Tag-X
  Kai-substrate, **noch nicht in main**; bis dahin: manueller
  podman-Run mit explicit env-vars).

Nach diesem Recipe laufen **parallel** zwei Tomás-Spawns
(Doppelbetrieb-Modus für die 4-Wochen-Pilot-Phase):

| Spawn | Stelle | Aufträge | Zweck |
|---|---|---|---|
| **Pre-Framework-Tomás** | Claude-Code-Sandbox auf Mira-Host | regulär Engineering | unverändert produktiv, Engineering läuft weiter |
| **Wakir-Runtime-Tomás** | Pilot-VM `wakir.test` Container | gleiche Aufträge als Schatten-Spawn | Vergleichs-Output, 4-Achsen-Score |

Der Bridge-Audit-Writer (PR #19 `2c1f3a6`) schreibt **beide** Outputs
in dieselben Sinks. Vergleich erfolgt 4 Wochen lang per Mira-Hand-
Score-Bilanz.

## 1. Vorbedingungen

Bevor du diese Recipe beginnst, müssen folgende Voraussetzungen erfüllt
sein:

| # | Voraussetzung | Quelle |
|---|---|---|
| V1 | Pilot-VM läuft Fedora-CoreOS 40+, SPIRE-Server + Agent + NATS via Quadlet aktiv | `PROXMOX_BRING_UP_RECIPE.md` durchlaufen, `proxmox-bringup-smoke` 6/6 PASS |
| V2 | Persona-Engine-Format-Spec v1.3 ratifiziert | PR #22 + #26 + #49 merged auf main |
| V3 | Persona-Converter byte-deterministisch | PR #23 merged, `wakir-persona-convert from-claude` smoke-grün |
| V4 | Pilot-Export-CLI verfügbar | dieser PR (Schritt 8): `cargo build --release -p persona-pilot-export` grün |
| V5 | Bridge-Audit-Writer aktiv | PR #19 `2c1f3a6` merged + Quadlet-Sidecar deployed (Kai Tag-N+) |
| V6 | Tomás-Pre-Framework-Spawn unverändert produktiv | aktueller Stand: kein Eingriff erforderlich |
| V7 | NATS-KV-Bucket-Init-Unit für `wakir-persona-state-tomas` | Kai Quadlet-Substanz Tag-N+ (manueller Bucket-Create-Workaround in §3 unten beschrieben) |

**Wenn V1-V7 nicht alle ✅**: STOP. Nicht weitermachen. Mira melden.

## 2. Schritt 8 — Persona-State-Export (Operator-Sandbox-Side)

Auf der **Operator-Sandbox** (nicht auf der Pilot-VM), CWD `/var/home/fred/AI-Corp`:

```bash
# (a) Build der Export-CLI (einmalig, ~30s):
cd wakir-runtime/wirelang-rust
cargo build --release -p persona-pilot-export

# (b) Export-Bundle für Tomás produzieren:
export EXPORT_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p /tmp/wakir-pilot-exports
./target/release/wakir-persona-pilot-export \
  --persona-def    /var/home/fred/AI-Corp/.claude/agents/dev-engineering.md \
  --workspace-dir  /var/home/fred/AI-Corp/agents-workspaces/dev-engineering/ \
  --out            /tmp/wakir-pilot-exports/tomas.pilot-export.json \
  --exported-at-utc "$EXPORT_TS"

# (c) V-907-Hash notieren (für Verify in §4):
jq -r '.v907_persona_hash' /tmp/wakir-pilot-exports/tomas.pilot-export.json
# Erwartet: sha256:<64hex>
```

**Verifikation:**

```bash
# Bundle ist JCS-valid + roundtrippable:
jq '.schema_version, .persona_id, .v907_persona_hash, .workspace_state_hash, .workspace_manifest.file_count' \
  /tmp/wakir-pilot-exports/tomas.pilot-export.json
# Erwartet:
# "wakir-pilot-export-v1"
# "dev-engineering"   (Hinweis: persona_id == frontmatter "name", nicht "tomas" — Pre-v1-Topology)
# "sha256:..."
# "sha256:..."
# <natürliche Zahl > 0>
```

**Hinweis zur `persona_id`:** Pre-Framework-Topologie nutzt
`name: dev-engineering` im Front-Matter (Tomás-Rolle-Slug). Wakir-
Persona-v1 wandelt das byte-deterministisch. Der Pilot-Spawn auf der
Pilot-VM nutzt `persona_id=dev-engineering` als Container-Name-Suffix
+ NATS-KV-Bucket-Suffix; das ist konsistent mit der ADR-0058-§Pilot-
Phase-Tomás-Bezeichnung.

## 3. Schritt 9a — Bundle-Transfer + NATS-KV-Bucket-Init (Pilot-VM)

```bash
# (a) Bundle auf die Pilot-VM kopieren (von der Operator-Sandbox aus):
scp /tmp/wakir-pilot-exports/tomas.pilot-export.json \
    operator@<pilot-vm-ip>:/var/lib/wakir/pilot-imports/

# (b) Bucket-Create auf der Pilot-VM (vorläufig, bis Kai's
#     bucket-init-Unit für die persona-state-Family in main ist):
ssh operator@<pilot-vm-ip>
sudo -u wakir nats kv add wakir-persona-state-dev-engineering \
  --history=10 --max-value-size=65536 --storage=file --replicas=1
```

**Verifikation:**

```bash
sudo -u wakir nats kv ls | grep wakir-persona-state-dev-engineering
# Erwartet: wakir-persona-state-dev-engineering (eine Zeile)
```

## 4. Schritt 9b — SPIFFE-SVID-Issuance für Tomás-Persona

Auf der Pilot-VM:

```bash
# (a) SPIRE-Registry-Entry für Tomás-Persona-Workload erstellen:
sudo -u wakir /opt/spire/bin/spire-server entry create \
  -spiffeID    spiffe://wakir.test/persona/dev-engineering \
  -parentID    spiffe://wakir.test/spire/agent/x509pop/$(sudo -u wakir /opt/spire/bin/spire-server agent list -format=json | jq -r '.agents[0].id_x509svid_serial_number') \
  -selector    unix:user:wakir \
  -selector    unix:label:wakir.persona.id:dev-engineering \
  -ttl         3600

# (b) SVID-Fetch testen (Workload-API-Pfad):
sudo -u wakir /opt/spire/bin/spire-agent api fetch x509 \
  -socketPath /run/spire/agent/api.sock \
  -write /tmp/tomas-svid/
```

**Verifikation:**

```bash
ls /tmp/tomas-svid/
# Erwartet: bundle.0.pem  svid.0.pem  svid.0.key
openssl x509 -in /tmp/tomas-svid/svid.0.pem -noout -subject -ext subjectAltName | head -3
# Erwartet (subjectAltName Zeile enthält):
#   URI:spiffe://wakir.test/persona/dev-engineering
```

## 5. Schritt 9c — Persona-Spawn (Container-Start)

**Wichtig:** Quadlet-Unit `wakir-persona-tomas.service` ist noch nicht
in main (Kai Sprint-9-Tag-X impl-axis). Bis dahin: manueller
`podman run`-Aufruf mit den Env-Vars die die zukünftige Quadlet-Unit
setzen wird (siehe persona-engine-format-spec §3.5 `container_bridge`):

```bash
# Persona-Hash aus Bundle holen für die V-907-pin-Verify:
PIN="$(jq -r '.v907_persona_hash' /var/lib/wakir/pilot-imports/tomas.pilot-export.json)"

# Wakir-Runtime-Tomás-Container starten (Schatten-Spawn):
sudo -u wakir podman run -d \
  --name wakir-persona-dev-engineering \
  --label "wakir.persona.id=dev-engineering" \
  --label "wakir.persona.hash=${PIN}" \
  --label "wakir.persona.schema_version=wakir-persona-v1" \
  --label "wakir.persona.pilot_mode=shadow" \
  -e WAKIR_PERSONA_ID=dev-engineering \
  -e WAKIR_PERSONA_HASH="${PIN}" \
  -e WAKIR_PERSONA_PILOT_MODE=shadow \
  -e NATS_URL=nats://127.0.0.1:4222 \
  -e SPIFFE_ENDPOINT_SOCKET=unix:///run/spire/agent/api.sock \
  -v /var/lib/wakir/pilot-imports/tomas.pilot-export.json:/etc/wakir/persona-export.json:ro,Z \
  -v /run/spire/agent/api.sock:/run/spire/agent/api.sock:ro \
  ghcr.io/wakir-labs/wakir-runtime-persona:latest \
  /usr/local/bin/wakir-persona-spawn --bundle /etc/wakir/persona-export.json
```

**Hinweis zum Bild-Tag `:latest`:** für die Pilot-Phase ist das
operativ ausreichend. Production-Cutover (ADR-0058 §Phase-4)
fordert einen pinned digest `@sha256:...`.

**Verifikation:**

```bash
# (a) Container läuft:
sudo -u wakir podman ps --filter name=wakir-persona-dev-engineering --format "{{.Names}} {{.Status}}"
# Erwartet: wakir-persona-dev-engineering Up <N> seconds

# (b) NATS-KV-Bucket hat den Spawn-Event:
sudo -u wakir nats kv ls wakir-persona-state-dev-engineering
# Erwartet: mind. 1 Key (spawn-event)

# (c) Container-Logs zeigen Bundle-Konsum + V-907-Verify:
sudo -u wakir podman logs wakir-persona-dev-engineering | head -20
# Erwartet (Substring-Match):
#   "v907_pin_verified=true"
#   "audit_trail_offset=<u64>"
#   "spawn_state=running"
```

## 6. Schritt 9d — Marker-Stack-Event (Pilot-Spawn-Signal)

Auf der Operator-Sandbox-Side ein Marker-Stack-Event in den
`wakir-marker-stack-acme`-Bucket einreichen (Sprint-6-Tag-9-Pattern):

```bash
cd /var/home/fred/AI-Corp/wakir-runtime
./target/release/wakir-marker-stack-emit \
  --bucket wakir-marker-stack-acme \
  --event-kind tomas-pilot-spawn \
  --persona-id dev-engineering \
  --metadata '{"v907":"<PIN>","exported_at_utc":"<EXPORT_TS>","pilot_phase":"shadow_doppelbetrieb","week":"1"}'
```

**Verifikation:**

```bash
sudo -u wakir nats kv get wakir-marker-stack-acme \
  --raw $(sudo -u wakir nats kv ls wakir-marker-stack-acme | tail -1) \
  | jq '.event_kind, .persona_id'
# Erwartet:
# "tomas-pilot-spawn"
# "dev-engineering"
```

## 7. Rollback-Pfad (Atomic, falls etwas schiefgeht)

**Triggers für sofortigen Rollback:**

- V-907-Pin-Verify im Container schlägt fehl (`v907_pin_verified=false`).
- Container-Spawn-State erreicht nicht `running` innerhalb 60s.
- SPIRE-SVID-Issuance schlägt fehl.
- NATS-KV-Bucket nicht erreichbar.

**Rollback-Sequenz (atomic, Pre-Framework bleibt unbeeinflusst):**

```bash
# (a) Wakir-Runtime-Tomás-Container stoppen + entfernen:
sudo -u wakir podman stop wakir-persona-dev-engineering
sudo -u wakir podman rm   wakir-persona-dev-engineering

# (b) NATS-KV-Bucket leeren (oder gleich löschen, da Pilot):
sudo -u wakir nats kv rm wakir-persona-state-dev-engineering -f

# (c) SPIRE-Registry-Entry entfernen:
sudo -u wakir /opt/spire/bin/spire-server entry delete \
  -entryID $(sudo -u wakir /opt/spire/bin/spire-server entry show \
    -spiffeID spiffe://wakir.test/persona/dev-engineering \
    -format json | jq -r '.entries[0].id')

# (d) Marker-Stack-Event für Rollback:
cd /var/home/fred/AI-Corp/wakir-runtime
./target/release/wakir-marker-stack-emit \
  --bucket wakir-marker-stack-acme \
  --event-kind tomas-pilot-rollback \
  --persona-id dev-engineering \
  --metadata '{"reason":"<one-liner>","pilot_phase":"aborted"}'
```

**Pre-Framework-Tomás-Spawn bleibt unverändert produktiv** — Engineering
läuft weiter ohne Unterbrechung.

## 8. Erfolgs-Kriterien (Schritt-9-Done-Definition)

- ✅ Container `wakir-persona-dev-engineering` läuft auf Pilot-VM.
- ✅ SPIRE-SVID `spiffe://wakir.test/persona/dev-engineering` issued + im Container abrufbar.
- ✅ NATS-KV-Bucket `wakir-persona-state-dev-engineering` hat mindestens 1 spawn-event.
- ✅ Container-Logs zeigen `v907_pin_verified=true`.
- ✅ Marker-Stack-Event `tomas-pilot-spawn` im `wakir-marker-stack-acme`-Bucket.
- ✅ Pre-Framework-Tomás-Spawn unverändert (Engineering läuft parallel).

**Wenn alle 6 ✅:** Schritt 9 done. Weiter mit Schritt 10
(`docs/migration-pilot-validation-phase-setup.md`).

## 9. Verbleibende Operator-Hand-Items (Pilot-Phase)

Während der 4-Wochen-Doppelbetrieb-Phase (ADR-0058 §Phase-2):

- Wöchentlich (Mo 09:00 CEST): 4-Achsen-Score-Bilanz Pre-Framework vs.
  Wakir-Runtime-Output (Mira-Hand).
- Wöchentlich (Mo 10:00 CEST): Henrik-Sample-Audit (1 Engineering-Auftrag).
- Täglich (passiv): Marker-Stack-Event-Konsistenz-Check via
  `wakir-marker-stack-verify`.

Sprint-9 Tag-N+ Items (Kai/Reza/Selin parallel):

- Quadlet-Unit `wakir-persona-tomas.service` (Kai impl-axis).
- NATS-KV-Bucket-Init-Unit für `wakir-persona-state-*`-Family (Kai).
- `NatsKvPersonaStateBacking` impl (Selin OI-PEF-13).
- Recovery-Drill-Scheduler (Selin OI-PEF-9 Quadlet-OnCalendar-Timer).

— Selin (pengine-eng) + Mira-Hand-Mitschrift
