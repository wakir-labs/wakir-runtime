<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Multi-Org-Onboarding-Recipe — `partner.test` als zweite Trust-Domain auf demselben Proxmox-Host

Status: Phase-2 Sprint-9 Tag-2 (Migrations-Schritt-1b, Multi-Org-
Extension auf `PROXMOX_BRING_UP_RECIPE.md`). Operator-Hand-Pfad
fuer den Aufsichtsrat. Sandbox-Boundary: dieses Dokument
beschreibt was der Operator (Fred) auf dem Proxmox-Host tut; die
Sandbox fuehrt keinen Live-Bring-up aus
(`feedback_sandbox_host_trennung.md`).

Companion-Artefakte:

- `PROXMOX_BRING_UP_RECIPE.md` — Single-Org-Pilot-Bring-up
  (Sprint-9 Tag-1, Voraussetzung fuer diese Recipe).
- `proxmox-bundle-v1.0.tar.gz` — Quadlet-Unit-Bundle, enthaelt
  bereits die `<SIDE>`-Placeholder-Templates fuer beide Sides
  (`wakir.test` + `partner.test`).
- `infra/spire/federation/README.md` — die hermetische Substrate-
  Beschreibung mit Cross-Trust-Domain-Bundle-Roundtrip.
- `bin/spire-fed-bundle` — Bundle-Export/Import-CLI (hermetic +
  Operator-Hand).

Lesepfad: dieser Recipe-Text ist **sequenziell**. Jeder Schritt
schliesst mit einer Verifikation; jede Verifikation hat einen
erwarteten Output. Bei einem Mismatch: VM-Snapshot zurueckrollen
(§7), nicht weiterklicken.

## 0. Was hier passiert (Ueberblick)

Wir erweitern den Single-Org-Pilot um eine zweite Trust-Domain
`partner.test`. Beide Trust-Domains laufen als getrennte SPIRE-
Server-Sides auf **demselben** Proxmox-Host (gleiche VM oder
separate VM — siehe §1 fuer die VM-Spec-Entscheidung). Die zwei
Sides foederieren ueber den dedizierten `wakir-federation`
Bridge-Netzwerk-Stack.

Nach diesem Recipe laufen acht systemd-Quadlet-Units parallel
(plus die NATS-Sidecars):

| Side | Server | Agent | NATS-KV-Bucket-Init |
|---|---|---|---|
| `wakir.test` | `wakir-spire-server-federation-wakir.service` | `wakir-spire-agent-wakir.service` | `wakir-nats-kv-bucket-init.service` |
| `partner.test` | `wakir-spire-server-federation-partner.service` | `wakir-spire-agent-partner.service` | (geteilte Unit — siehe §3) |

Plus zwei einmalige Bundle-Cross-Import-Operationen (§4):

- `wakir.test` exportiert das eigene Trust-Bundle → `partner.test`
  importiert es als foreign-trust-bundle.
- `partner.test` exportiert das eigene Trust-Bundle → `wakir.test`
  importiert es als foreign-trust-bundle.

Steady-state nach Cross-Import: jede Side fetcht die andere
Bundle-Endpoint kontinuierlich ueber den Bundle-Endpoint-Listener
(`https_spiffe`-Profil). Cross-Trust-Domain SVIDs werden gegen
das jeweils importierte foreign-trust-bundle verifiziert.

### Single-VM vs. Two-VM-Layout

| Layout | Empfehlung | Begruendung |
|---|---|---|
| **Single-VM (Default Pilot)** | Beide Sides auf derselben VM, je 0.5 cpu / 256 MiB cgroup-Limit; Network-Bridge isoliert die Sides | Pilot-Phase, einfacher Operator-Hand-Pfad, alle Container auf einem Host; deckt 80% der Multi-Org-Federation-Mechanik ab |
| **Two-VM (Production-Shadow)** | Eine VM pro Side; Cross-Side ueber Host-Port-Bridge `127.0.0.1:8443/8444` | Production-Shadow, jede Org auf eigener VM (HA-Setup), Cross-Side-Latenz realistisch (Host-Port-Roundtrip statt Bridge-Network-DNS) |

**Default fuer den Pilot:** Single-VM. Two-VM ist Sprint-10+
Thema (Production-Shadow-Pilot mit echtem `<FTD-ID>.wakir.dev`-
Trust-Domain).

### Trust-Domain-Wahl

Wir nutzen `partner.test` als zweite Trust-Domain (RFC-6761 §6.5
`.test`-Reservierung; hermetic-only). Die Phase-3a-Produktions-
Trust-Domain `<FTD-ID>.wakir.dev` ist explizit **noch nicht
Thema** — keine Live-DNS, keine Production-CA.

### Sandbox vs. Operator-Hand-Grenze

| Phase | Wer | Wo |
|---|---|---|
| Spec/Code-Bauen | Sandbox (Kai, Reza, Tomás) | wakir-runtime-Repo, hermetische Tests |
| Bundle-Tarball-Build | Sandbox | `build-bundle.sh` deterministisch |
| Image-Pin-Aufloesung | Operator-Hand (Tomás Cross-Review) | `cosign verify` auf Host |
| VM-Erstellung / Erweiterung | Operator-Hand (Fred) | Proxmox-Web-UI |
| Quadlet-Install Partner-Side | Operator-Hand (Fred) | SSH auf VM, `sudo systemctl ...` |
| Bundle-Cross-Import | Operator-Hand (Fred) | `bin/spire-fed-bundle export/import` |
| Cross-Trust-SVID-Verify | Operator-Hand (Fred) | `bin/proxmox-bringup-smoke --multi-org` |
| Rollback | Operator-Hand (Fred) | Proxmox-Web-UI, VM-Snapshot |

## 1. Voraussetzung: Single-Org-Pilot laeuft

Bevor Multi-Org-Onboarding startet:

```bash
# Auf der Pilot-VM:
systemctl --no-pager status wakir-spire-server-federation-wakir.service \
    wakir-spire-agent-wakir.service wakir-nats.service \
    wakir-nats-kv-bucket-init.service
# Erwartet: alle Long-Running active (running); Bucket-Init inactive (dead)
# nach successful run; kein failed-State.
```

```bash
bin/proxmox-bringup-smoke --org acme
# Erwartet: SUMMARY 6/6 PASS
```

Wenn die Single-Org-Pilot-Health nicht steht: **STOP** und zuerst
das `PROXMOX_BRING_UP_RECIPE.md` durchspielen, nicht hier
weitermachen.

**Snapshot:** `qm snapshot 101 pre-multi-org-onboard` bevor du
weitergehst. Dieser Snapshot ist die Rollback-Baseline fuer den
gesamten Multi-Org-Onboarding-Pfad.

## 2. VM-Vorbereitung (Single-VM-Pfad)

### 2.1 Resource-Headroom pruefen

Single-VM-Pfad: die existierende Pilot-VM muss zusaetzliche
Resources fuer den partner-Side haben. Empfehlung:

| Resource | Single-Org-Pilot | Multi-Org-Erweiterung | Delta |
|---|---|---|---|
| vCPU | 4 | 6 | +2 |
| RAM | 4 GiB | 6 GiB | +2 GiB |
| Disk | 32 GiB | 48 GiB | +16 GiB |

Auf dem Proxmox-Host:

```bash
qm set 101 --cores 6 --memory 6144
qm resize 101 scsi0 +16G
qm shutdown 101 && qm start 101
```

Verifikation in der VM:

```bash
nproc                                  # erwartet: 6
free -h | awk '/^Mem:/ { print $2 }'   # erwartet: ~6Gi
df -h / | tail -1                      # erwartet: gewachsen auf ~48G
```

### 2.2 Two-VM-Pfad (Alternative)

Wenn der Operator den Two-VM-Pfad bevorzugt:

```bash
# Auf dem Proxmox-Host: klone die Pilot-VM als Template,
# erstelle eine zweite VM 102 fuer die partner-Side.
qm clone 101 102 --name wakir-partner-pilot --full
qm set 102 --cores 4 --memory 4096
qm start 102
```

Two-VM erfordert zusaetzliche Port-Bridge-Routen zwischen den
beiden VMs (host-loopback-only). Dieser Pfad ist Sprint-10+
Thema und in diesem Recipe nicht weiter ausgefuehrt.

**Snapshot:** `qm snapshot 101 post-multi-org-resource-bump`.

## 3. Quadlet-Install Partner-Side

Auf der VM, im Bundle-Verzeichnis (`/opt/wakir-runtime/`):

### 3.1 SPIRE-Server-Partner-Side

```bash
# Substituiere den partner-side aus dem Quadlet-Template.
sudo sed -e 's/<SIDE>/partner/g' \
    -e 's/<HOST_BUNDLE_PORT>/8444/g' \
    -e 's/<HOST_GRPC_PORT>/8083/g' \
    /opt/wakir-runtime/infra/spire/federation/quadlet/wakir-spire-server-federation.container \
    | sudo tee /etc/containers/systemd/wakir-spire-server-federation-partner.container

# Volume-Templates (per-side benannt).
for vol in data sockets bundles; do
    sudo sed -e 's/<SIDE>/partner/g' \
        /opt/wakir-runtime/infra/spire/federation/quadlet/wakir-spire-server-federation-${vol}.volume \
        | sudo tee /etc/containers/systemd/wakir-spire-server-federation-partner-${vol}.volume
done

# Config-Datei (partner-side, byte-precision-mirror auf wakir-side mit
# trust-domain `partner.test` statt `wakir.test`).
sudo install -m 644 \
    /opt/wakir-runtime/infra/spire/federation/config/spire-server-partner.conf \
    /etc/wakir/spire-federation/spire-server-partner.conf

# Image-Pin-Aufloesung (Cross-Review Zone-C, dasselbe Verfahren wie
# wakir-side; bei bereits aufgeloestem wakir-side-Pin Re-Use).
sudo /opt/wakir-runtime/infra/spire/federation/proxmox/resolve-image-pins.sh \
    --apply /etc/containers/systemd/wakir-spire-server-federation-partner.container

sudo systemctl daemon-reload
sudo systemctl start wakir-spire-server-federation-partner.service
```

Verifikation:

```bash
systemctl --no-pager status wakir-spire-server-federation-partner.service
# Erwartet: Active: active (running); Health: healthy

podman exec wakir-spire-server-federation-partner spire-server healthcheck
# Erwartet: Server is healthy.
```

### 3.2 SPIRE-Agent-Partner-Side

```bash
sudo sed -e 's|<SIDE>|partner|g' \
    -e 's|<TRUST_DOMAIN>|partner.test|g' \
    -e 's|<SERVER_DNS>|spire-server-partner|g' \
    /opt/wakir-runtime/infra/spire/agent/quadlet/wakir-spire-agent-federation.container \
    | sudo tee /etc/containers/systemd/wakir-spire-agent-partner.container

for vol in data sockets; do
    sudo sed -e 's/<SIDE>/partner/g' \
        /opt/wakir-runtime/infra/spire/agent/quadlet/wakir-spire-agent-federation-${vol}.volume \
        | sudo tee /etc/containers/systemd/wakir-spire-agent-partner-${vol}.volume
done

sudo install -m 644 \
    /opt/wakir-runtime/infra/spire/agent/config/spire-agent-partner.conf \
    /etc/wakir/spire-agent-partner.conf

sudo systemctl daemon-reload
sudo systemctl start wakir-spire-agent-partner.service
```

Verifikation:

```bash
systemctl --no-pager status wakir-spire-agent-partner.service
# Erwartet: Active: active (running)

podman exec wakir-spire-agent-partner spire-agent healthcheck
# Erwartet: Agent is healthy.
```

### 3.3 NATS-KV-Bucket-Provisioning Partner-Side

Der NATS-Cluster + die `wakir-nats-kv-bucket-init.service` Unit
sind shared zwischen den Sides — partner-side bekommt einfach
einen weiteren Eintrag im `/etc/wakir/onboarded-orgs`-Roster:

```bash
# Bestehende Roster lesen (acme-only).
cat /etc/wakir/onboarded-orgs
# Erwartet:
#   acme

# Partner-org-id anhaengen.
echo 'partner' | sudo tee -a /etc/wakir/onboarded-orgs

# Re-run der bucket-init Unit; idempotent fuer acme, created fuer
# partner.
sudo systemctl start wakir-nats-kv-bucket-init.service
```

Verifikation:

```bash
journalctl -u wakir-nats-kv-bucket-init.service --since '1 min ago' \
    | tail -15
# Erwartet (excerpt):
#   [nats-kv-bucket-provision] org=acme bucket=wakir-marker-stack-acme: unchanged
#   [nats-kv-bucket-provision] org=partner bucket=wakir-marker-stack-partner: created
```

**Reza-Tag-2-Erweiterung (Sprint-9 Tag-2):** sobald Reza-PR #25
gemerged ist, provisioniert dieselbe Unit AUCH die per-org
`wakir-caveat-override-export-sequence-{org_id}`-Bucket-Family:

```text
# Erwartet (excerpt nach Reza-Tag-2-Merge):
#   [nats-kv-bucket-provision] org=acme bucket=wakir-marker-stack-acme: unchanged
#   [nats-kv-bucket-provision] org=acme bucket=wakir-caveat-override-export-sequence-acme: created
#   [nats-kv-bucket-provision] org=partner bucket=wakir-marker-stack-partner: created
#   [nats-kv-bucket-provision] org=partner bucket=wakir-caveat-override-export-sequence-partner: created
```

Die Family-Registry ist defensive: solange Reza-Tag-2 nicht
gemerged ist, provisioniert die Unit weiterhin nur die
`marker-stack`-Family. Cross-Review Zone-B (siehe §6) deckt das
Konsens-Trail ab.

**Snapshot:** `qm snapshot 101 post-partner-quadlet`.

## 4. Bundle-Cross-Import (`spire-fed-bundle`)

Steady-state Federation erfordert, dass jede Side die
foreign-trust-bundle der anderen Side kennt. Initial-Bootstrap:
manueller Export/Import-Roundtrip.

### 4.1 Bundle-Export wakir.test → partner.test

```bash
# Export wakir.test trust-bundle aus der wakir-side.
podman exec wakir-spire-server-federation-wakir \
    /opt/spire/bin/spire-server bundle list -format spiffe > /tmp/wakir-bundle.jwks

# Cross-Verify (hermetic): check the exported JWKS is well-formed.
/opt/wakir-runtime/bin/spire-fed-bundle import \
    --from-file /tmp/wakir-bundle.jwks \
    --as-trust-domain wakir.test \
    --out /tmp/wakir-bundle-verified.jwks
# Erwartet: keine error; spire-fed-bundle exit 0.

# Import in partner.test side.
podman cp /tmp/wakir-bundle.jwks \
    wakir-spire-server-federation-partner:/tmp/wakir-bundle.jwks
podman exec wakir-spire-server-federation-partner \
    /opt/spire/bin/spire-server bundle set \
    -id spiffe://wakir.test \
    -path /tmp/wakir-bundle.jwks
# Erwartet:
#   bundle set successfully
```

### 4.2 Bundle-Export partner.test → wakir.test

```bash
podman exec wakir-spire-server-federation-partner \
    /opt/spire/bin/spire-server bundle list -format spiffe > /tmp/partner-bundle.jwks

/opt/wakir-runtime/bin/spire-fed-bundle import \
    --from-file /tmp/partner-bundle.jwks \
    --as-trust-domain partner.test \
    --out /tmp/partner-bundle-verified.jwks
# Erwartet: keine error; spire-fed-bundle exit 0.

podman cp /tmp/partner-bundle.jwks \
    wakir-spire-server-federation-wakir:/tmp/partner-bundle.jwks
podman exec wakir-spire-server-federation-wakir \
    /opt/spire/bin/spire-server bundle set \
    -id spiffe://partner.test \
    -path /tmp/partner-bundle.jwks
# Erwartet:
#   bundle set successfully
```

### 4.3 Bundle-List-Verifikation auf beiden Sides

```bash
# wakir-side hat jetzt sowohl die eigene als auch die partner-side
# Bundle eingetragen.
podman exec wakir-spire-server-federation-wakir \
    /opt/spire/bin/spire-server bundle list
# Erwartet (excerpt):
#   ****************************************
#   * spiffe://wakir.test (own)
#   ****************************************
#   ****************************************
#   * spiffe://partner.test (foreign)
#   ****************************************

# Spiegelbild auf partner-side.
podman exec wakir-spire-server-federation-partner \
    /opt/spire/bin/spire-server bundle list
# Erwartet (excerpt):
#   ****************************************
#   * spiffe://partner.test (own)
#   ****************************************
#   ****************************************
#   * spiffe://wakir.test (foreign)
#   ****************************************
```

Falls eine Side die foreign-bundle nicht kennt: Bundle-Set-Step
oben wiederholen, ggf. erst Container-Path mit `podman cp`
prufen. **Kein** weiterer Schritt bevor beide Sides beide Bundles
gelistet haben.

**Snapshot:** `qm snapshot 101 post-bundle-cross-import`.

## 5. Cross-Trust-Domain-SVID-Verify-Smoke

Nach Cross-Import kann jede Side gegen einen SVID der anderen
Side verifizieren. Smoke-Test:

```bash
bin/proxmox-bringup-smoke --org partner --multi-org
# Erwartet: SUMMARY 9/9 PASS
# Checks 1-6 wie Single-Org-Pilot, plus:
#   7. partner-spire-server-healthy
#   8. partner-spire-agent-healthy
#   9. cross-trust-svid-verify
```

**Wichtig:** der `--multi-org` Flag ist eine Erweiterung des
Single-Org-Smoke-Skripts; er triggert die drei zusaetzlichen
Partner-Side-Checks. Wenn der Flag fehlt, laeuft das Skript im
Single-Org-Mode (6 Checks) und ignoriert die partner-Units.

## 6. Cross-Review-Trail

| Zone | Counterparty | Was | Status |
|---|---|---|---|
| Zone A | Reza (Wirelang) | SPIFFE-Trust-Domain-Literal `partner.test` (hermetic-only; Phase-3a `<FTD-ID>.wakir.dev` nicht Pilot-Scope) | Konsens 2026-05-11 (Sprint-6 Tag-6, Z-A-Marker-Set Aisha) |
| Zone B | Reza (NATS-Schema) | per-org Multi-Family-Bucket-Provisioning: `wakir-marker-stack-{org_id}` (Sprint-8 Tag-4) + `wakir-caveat-override-export-sequence-{org_id}` (Sprint-9 Tag-2, PR #25); Family-Registry defensive bis Reza-Tag-2-Merge | Cross-Review-Ack Sprint-9 Tag-2 (dieser Recipe); Aisha-Konsens-Marker-Set after PR #25 merge |
| Zone C | Tomás (OTS / Image-Pipeline) | Cosign-Pin-Resolve fuer SPIRE-Server/Agent + python:3.13-slim (re-use Single-Org-Pilot-Pins) | Konsens 2026-05-07 (Sprint-3 Tomás Zone-C-NATS-Image-Pin-Ack) |
| Zone D | Reza (V-904 Identity-Bridge) | nicht in Pilot-Scope (Phase-3) | Reserved |

## 7. Rollback

Snapshot-Kette:

1. `pre-multi-org-onboard` (vor §1) — voller Rollback auf
   Single-Org-Pilot, partner-side komplett weg.
2. `post-multi-org-resource-bump` (nach §2) — Resource-Bump
   bleibt, Quadlet noch unangetastet.
3. `post-partner-quadlet` (nach §3) — beide Sides laufen, aber
   Bundle-Cross-Import noch nicht.
4. `post-bundle-cross-import` (nach §4) — voll funktionsfaehig.

Rollback-Befehl:

```bash
qm shutdown 101 && qm rollback 101 <snapshot-name> && qm start 101
```

Nach Rollback: `bin/proxmox-bringup-smoke --org acme` zur
Validierung; bei `--multi-org` Rollback ohne Single-Org-Touch
sollte `bin/proxmox-bringup-smoke --org acme` 6/6 PASS bleiben.

## 8. Was Multi-Org-Pilot NICHT abdeckt

- **Kein Phase-3a-Production-Trust-Domain.** Wir bleiben auf
  `partner.test`. Live-`<FTD-ID>.wakir.dev` ist Sprint-10+-Thema.
- **Kein Two-VM-Production-Shadow.** Single-VM-Layout deckt den
  Federation-Pfad ab; Two-VM ist Sprint-10+ paired mit echtem
  DNS/Production-CA.
- **Kein SPIFFE-JWT-SVID-NATS-Auth.** Phase-1b NATS bleibt offen
  (loopback-only); Token-Auth ist Phase-2.4-Substrate.
- **Kein Cosign-Pin-Refresh.** Die Partner-Side re-used die
  Single-Org-Pilot Image-Pins (SPIRE-Server-1.14.6, Agent-1.14.6,
  python:3.13-slim); kein Pin-Bump ueber den Multi-Org-Onboard
  hinaus.
- **Kein TEE-Attestation** (V-904 Phase-3-Substrate).

## 9. Anbindung an die Hermetische Substrate

Das hermetische Compose-Substrate
(`compose/spire-federation.yaml`) hat bereits beide Sides
(`spire-server-wakir` + `spire-server-partner`) — die Quadlet-
Units, die wir hier installieren, sind die byte-precision-Mirror
davon (Drift-Test in `tests/orchestrator/test_quadlet_*.py`
greift, falls Compose und Quadlet auseinanderdriften).

Die Multi-Family-Bucket-Registry im `nats-kv-bucket-provision`
Driver greift auch in der Sandbox (hermetic-Tests
`tests/orchestrator/test_nats_kv_bucket_provision_multi_family.py`).
Defensive-Import-Mode: wenn das Reza-Tag-2-Modul nicht da ist,
provisioniert die Unit nur die marker-stack-Family — kein
Hard-Failure.

## 10. Kontakt + Cross-Review-Trail

| Zone | Counterparty | Was |
|---|---|---|
| Zone A | Reza (Wirelang) | SPIFFE-Trust-Domain-Literale (`wakir.test` + `partner.test` ok, `wakir.dev` Phase-3) |
| Zone B | Reza (NATS-Schema) | Multi-Family-Bucket-Provisioning: marker-stack (Sprint-8 Tag-4 owner) + sequence-ledger (Sprint-9 Tag-2 owner) |
| Zone C | Tomás (OTS / Image-Pipeline) | Cosign-Pin-Resolve re-use Single-Org-Pilot |
| Zone D | Reza (V-904 Identity-Bridge) | nicht in Pilot-Scope (Phase-3) |

Aisha protokolliert Konsens-Zeitpunkte. Bei Bring-up-Block:
Spawn-Return mit Diagnose an Kai (Outbox-Rapport-Pfad).

— Kai
