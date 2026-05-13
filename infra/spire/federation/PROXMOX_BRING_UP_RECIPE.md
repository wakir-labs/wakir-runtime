<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Proxmox-VM Bring-up-Recipe — Phase-1b Single-Org-Pilot

Status: Phase-2 Sprint-9 Tag-1 (Migrations-Schritt-1). Operator-Hand-
Pfad fuer den Aufsichtsrat-Bring-up auf Proxmox. Sandbox-Boundary:
dieses Dokument beschreibt was der Operator (Fred) auf dem Proxmox-
Host tut; die Sandbox fuehrt keinen Live-Bring-up aus
(`feedback_sandbox_host_trennung.md`).

Companion-Artefakte:

- `proxmox-bundle-v1.0.tar.gz` — Quadlet-Unit-Bundle (alle
  `.container`/`.network`/`.volume`-Units plus Placeholder-
  Resolution-Skript).
- `bin/proxmox-bringup-smoke` — Operator-Hand-Self-Verify nach
  Bring-up (alle Quadlet-Units aktiv, NATS-KV erreichbar,
  SPIRE-Workload-API ok).
- `infra/spire/federation/README.md` — die hermetische Substrate-
  Beschreibung (Compose + Quadlet, kein Live-Pfad).

Lesepfad: dieser Recipe-Text ist **sequenziell**. Jeder Schritt
schliesst mit einer Verifikation; jede Verifikation hat einen
erwarteten Output. Bei einem Mismatch: VM-Snapshot zurueckrollen
(§7), nicht weiterklicken.

## 0. Was hier passiert (Ueberblick)

Wir bringen auf einem Proxmox-Host eine Single-Org-Pilot-VM hoch,
auf der vier Container-Workloads parallel laufen:

1. **NATS-JetStream** (`wakir-nats`) — der Phase-1b Message-Bus.
2. **SPIRE-Server-Federation** (`wakir-spire-server-federation-wakir`)
   — der Workload-Identity-Aussteller fuer die `wakir.test`
   Trust-Domain.
3. **SPIRE-Agent-Federation** (`wakir-spire-agent-wakir`) — der
   Agent-Sidecar, der Workload-API-Sockets bereitstellt.
4. **NATS-KV-Bucket-Init** (`wakir-nats-kv-bucket-init`) — der
   einmalige Provisioner, der pro Org einen Marker-Stack-Bucket
   anlegt (Sprint-8 Tag-4 / Sprint-9 Tag-1).

Alle vier laufen als systemd-Quadlet-Units auf Podman. Es gibt
keinen Compose-Aufruf im Live-Pfad — Compose bleibt das
hermetische Test-Substrate.

### Trust-Domain (Phase-1b-Pilot)

Wir nutzen `wakir.test` als Trust-Domain (RFC-6761 §6.5 `.test`-
Reservierung; hermetic-only). Die Phase-3a-Produktions-Trust-
Domain `<FTD-ID>.wakir.dev` ist explizit **noch nicht Thema** —
keine Live-DNS, keine Production-CA. Wir bauen das Pilot-System
ueber `wakir.test`, validieren die SVID-Roundtrip-Mechanik, und
heben spaeter (Sprint-10+) auf die Produktions-Trust-Domain.

### Sandbox vs. Operator-Hand-Grenze

| Phase | Wer | Wo |
|---|---|---|
| Spec/Code-Bauen | Sandbox (Kai, Reza, Tomás) | wakir-runtime-Repo, hermetische Tests |
| Image-Pin-Aufloesung | Operator-Hand (Tomás Cross-Review) | `cosign verify` auf Host |
| VM-Erstellung | Operator-Hand (Fred) | Proxmox-Web-UI |
| Quadlet-Install | Operator-Hand (Fred) | SSH auf VM, `sudo systemctl ...` |
| Smoke-Verify | Operator-Hand (Fred) | `bin/proxmox-bringup-smoke` auf VM |
| Rollback | Operator-Hand (Fred) | Proxmox-Web-UI, VM-Snapshot |

## 1. Vorbereitung auf dem Proxmox-Host

### 1.1 VM-Spec-Empfehlung

Single-Org-Pilot, vier parallele Container-Workloads, kein
externes Traffic-Pattern:

| Resource | Empfehlung | Begruendung |
|---|---|---|
| OS | Fedora-CoreOS 40+ (stable) | rpm-ostree + Podman-Quadlet-First; ALTERNATIVE: Debian-12+Podman-4.4+ |
| vCPU | 4 cores | NATS+SPIRE-Server+Agent+Provisioner gleichzeitig; je 0.5 cpu cgroup-Limit |
| RAM | 4 GiB | NATS 512 MiB + SPIRE-Server 256 MiB + Agent 256 MiB + Provisioner 256 MiB + Headroom |
| Disk | 32 GiB (thin-provisioned) | JetStream-Store waechst langsam (Marker-Events 32 KiB max); +20 GiB Headroom |
| Netzwerk | 1 NIC (vmbr0), DHCP oder Static-IP | nur Loopback-Ports public, keine Inbound-Ports von extern |
| Snapshot | aktiviert | jeder Schritt unten endet mit Snapshot-Empfehlung |

**Fedora-CoreOS als Default**: Atomic-Distro, native Quadlet-
Integration ohne Distro-Reibung, `rpm-ostree status` zeigt jedes
Update sauber. Falls Fred Debian bevorzugt: Debian-12 mit
`podman` aus Backports (Podman 4.4+) reicht — dann muessen die
Quadlet-Units allerdings nach `/etc/containers/systemd/`
manuell installiert werden (CoreOS macht das gleiche, aber mit
Ignition-Unterstuetzung).

### 1.2 Pre-Flight

Auf dem Proxmox-Host (nicht in der VM!) — Verifikation, dass die
Substrate stehen:

```bash
# Proxmox-Version
pveversion
# Erwartet: pve-manager/8.x oder pve-manager/7.x

# Verfuegbare Storage-Pools
pvesm status
# Erwartet: mindestens ein Pool mit >32 GiB Free

# Verfuegbare Netzwerk-Bridges
ip link show type bridge
# Erwartet: vmbr0 oder Equivalent
```

### 1.3 VM-Erstellung

Via Proxmox-Web-UI **oder** via CLI auf dem Proxmox-Host. CLI-
Variante mit Fedora-CoreOS-Image (substituiert Operator-Hand die
gewuenschte VMID 101 und das gewuenschte Storage-Target):

```bash
# Auf dem Proxmox-Host (NICHT in der Sandbox):
VMID=101
STORAGE=local-lvm
ISO=fedora-coreos-40-stable.iso     # vorher nach /var/lib/vz/template/iso/ hochgeladen

qm create $VMID \
  --name wakir-pilot \
  --memory 4096 \
  --cores 4 \
  --net0 virtio,bridge=vmbr0 \
  --scsihw virtio-scsi-single \
  --scsi0 $STORAGE:32 \
  --cdrom local:iso/$ISO \
  --boot c --bootdisk scsi0 \
  --ostype l26 \
  --agent enabled=1

qm start $VMID
# Konsole oeffnen (Proxmox-Web-UI > VM > Console) und installieren.
```

**Verifikation:**

```bash
qm status $VMID
# Erwartet: status: running
```

**Snapshot vor allem Weiteren:**

```bash
qm snapshot $VMID pre-bring-up --description "Vor Container-Bring-up"
```

## 2. Quadlet-Bundle auf die VM bringen

Ab hier alle Befehle innerhalb der VM via SSH oder Console.

### 2.1 Repo-Klon + Bundle-Resolve

```bash
sudo dnf install -y git podman    # Fedora-CoreOS hat das schon
sudo mkdir -p /opt
sudo git clone https://github.com/wakir-labs/wakir-runtime.git /opt/wakir-runtime
cd /opt/wakir-runtime
```

**Verifikation:**

```bash
ls /opt/wakir-runtime/quadlet/
# Erwartet: wakir-nats.container, wakir-spire-server.container,
#           wakir-spire-agent.container, wakir-nats-kv-bucket-init.container,
#           wakir-orchestrator.network, *-data.volume, *-sockets.volume

ls /opt/wakir-runtime/infra/spire/federation/quadlet/
# Erwartet: wakir-spire-server-federation.container,
#           wakir-federation.network, *-bundles.volume, etc.
```

### 2.2 Bundle-Tarball entpacken (Alternative zu Repo-Klon)

Falls Fred das gepackte Tarball bevorzugt (keine Git-Abhaengigkeit):

```bash
# Tarball nach /tmp uebertragen (scp vom Operator-Laptop):
sudo tar -xzf /tmp/proxmox-bundle-v1.0.tar.gz -C /opt
# Erwartet: /opt/wakir-runtime/{quadlet,infra,bin,...}
```

**Verifikation:**

```bash
sha256sum /tmp/proxmox-bundle-v1.0.tar.gz
# Erwartet: identisch zu /opt/wakir-runtime/infra/spire/federation/proxmox-bundle-v1.0.sha256
```

## 3. Image-Pin-Aufloesung (Cross-Review Zone-C, Tomás-Track)

Vor Live-Bring-up loest Operator-Hand die `DIGEST_PENDING_TOMAS_REVIEW`-
Platzhalter zu echten sha256-Digests auf. Dieser Schritt ist
**Cross-Review-pflicht** und MUSS vor jeder weiteren Schritt-Aktion
laufen — sonst startet Podman die Container mit nicht-pinned-Image-
Tags, was unsere Reproduzierbarkeits-Invariante bricht.

### 3.1 cosign verify

```bash
sudo dnf install -y cosign
# Falls nicht in der Distro-Repo: cosign-Release-Binary von
# https://github.com/sigstore/cosign/releases (200-verifiziert).

cosign verify \
  --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  ghcr.io/spiffe/spire-server:1.14.6

cosign verify \
  --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  ghcr.io/spiffe/spire-agent:1.14.6
```

**Erwartet:** `docker-manifest-digest`-Feld mit `sha256:<64-hex>`-
Eintrag in der JSON-Ausgabe. Cross-Check via `skopeo inspect`:

```bash
sudo dnf install -y skopeo
skopeo inspect docker://ghcr.io/spiffe/spire-server:1.14.6 | jq -r '.Digest'
skopeo inspect docker://ghcr.io/spiffe/spire-agent:1.14.6 | jq -r '.Digest'
```

Beide Werte (cosign-Output + skopeo-Output) MUESSEN
byte-identisch sein. Falls nicht: **STOP**, Cross-Review-Eskalation
an Tomás. Snapshot zurueckrollen.

### 3.2 Placeholder-Resolution mit Skript

Das Bundle bringt ein deterministisches sed-basierten
Resolution-Skript mit:

```bash
sudo /opt/wakir-runtime/infra/spire/federation/proxmox/resolve-image-pins.sh \
  --spire-server-digest sha256:<wert-aus-cosign> \
  --spire-agent-digest sha256:<wert-aus-cosign> \
  --python-digest sha256:<wert-aus-cosign-fuer-python:3.13-slim> \
  --apply
# Erwartet: Output listet jede ersetzte Datei mit alter und neuer Zeile.
```

**Verifikation:**

```bash
grep -rn DIGEST_PENDING_TOMAS_REVIEW /opt/wakir-runtime/quadlet/ \
  /opt/wakir-runtime/infra/spire/
# Erwartet: keine Treffer mehr (alle Platzhalter aufgeloest).
```

**Snapshot nach diesem Schritt:**

```bash
# Auf dem Proxmox-Host:
qm snapshot 101 post-image-pin --description "Nach Cosign-Pin-Resolve"
```

## 4. Quadlet-Install + Trust-Domain-Bootstrap

### 4.1 Network-Sidecar und Volumes

```bash
# Orchestrator-Bridge-Netzwerk:
sudo install -m 644 /opt/wakir-runtime/quadlet/wakir-orchestrator.network \
  /etc/containers/systemd/wakir-orchestrator.network

# Federation-Bridge-Netzwerk:
sudo install -m 644 /opt/wakir-runtime/infra/spire/federation/quadlet/wakir-federation.network \
  /etc/containers/systemd/wakir-federation.network

# NATS + SPIRE-Server + SPIRE-Agent volumes:
for vol in \
  /opt/wakir-runtime/quadlet/wakir-nats-jetstream-data.volume \
  /opt/wakir-runtime/quadlet/wakir-spire-server-data.volume \
  /opt/wakir-runtime/quadlet/wakir-spire-server-sockets.volume \
  /opt/wakir-runtime/quadlet/wakir-spire-agent-data.volume \
  /opt/wakir-runtime/quadlet/wakir-spire-agent-sockets.volume \
; do
  sudo install -m 644 "$vol" /etc/containers/systemd/
done

# Federation-Server volumes (wakir-Side):
for vol in \
  /opt/wakir-runtime/infra/spire/federation/quadlet/wakir-spire-server-federation-data.volume \
  /opt/wakir-runtime/infra/spire/federation/quadlet/wakir-spire-server-federation-sockets.volume \
  /opt/wakir-runtime/infra/spire/federation/quadlet/wakir-spire-server-federation-bundles.volume \
; do
  # Per-Side-Substitution: <SIDE> → wakir
  sed -e 's/<SIDE>/wakir/g' "$vol" \
    | sudo tee /etc/containers/systemd/$(basename "$vol" | sed 's/<SIDE>/wakir/g') >/dev/null
done

sudo systemctl daemon-reload
```

**Verifikation:**

```bash
ls /etc/containers/systemd/
# Erwartet: 2x .network, 6x+3x .volume (Single-Side wakir-Pilot)
```

### 4.2 SPIRE-Server-Federation-Container (wakir-Side)

```bash
# Per-Side-Substitution: wakir.test bekommt host-port 8443 + 8082.
sed -e 's/<SIDE>/wakir/g' \
    -e 's/<HOST_BUNDLE_PORT>/8443/g' \
    -e 's/<HOST_GRPC_PORT>/8082/g' \
    /opt/wakir-runtime/infra/spire/federation/quadlet/wakir-spire-server-federation.container \
  | sudo tee /etc/containers/systemd/wakir-spire-server-federation-wakir.container >/dev/null

# Config-File bind-mount target:
sudo install -d -m 755 /etc/wakir/spire-federation
sudo install -m 644 \
  /opt/wakir-runtime/infra/spire/federation/config/spire-server-wakir.conf \
  /etc/wakir/spire-federation/spire-server-wakir.conf

sudo systemctl daemon-reload
sudo systemctl start wakir-spire-server-federation-wakir.service
```

**Verifikation:**

```bash
systemctl status wakir-spire-server-federation-wakir.service
# Erwartet: Active: active (running)

sudo podman healthcheck run wakir-spire-server-federation-wakir
# Erwartet: exit 0, kein Output

sudo podman exec wakir-spire-server-federation-wakir \
  /opt/spire/bin/spire-server healthcheck
# Erwartet: "Server is healthy."
```

### 4.3 SPIRE-Agent-Federation-Container (wakir-Side)

```bash
# Per-Side-Substitution:
sed -e 's|<SIDE>|wakir|g' \
    -e 's|<TRUST_DOMAIN>|wakir.test|g' \
    -e 's|<SERVER_DNS>|spire-server-wakir|g' \
    /opt/wakir-runtime/infra/spire/agent/quadlet/wakir-spire-agent-federation.container \
  | sudo tee /etc/containers/systemd/wakir-spire-agent-wakir.container >/dev/null

# Per-Side-Volumes:
for vol in \
  /opt/wakir-runtime/infra/spire/agent/quadlet/wakir-spire-agent-federation-data.volume \
  /opt/wakir-runtime/infra/spire/agent/quadlet/wakir-spire-agent-federation-sockets.volume \
; do
  sed -e 's/<SIDE>/wakir/g' "$vol" \
    | sudo tee /etc/containers/systemd/$(basename "$vol" | sed 's/<SIDE>/wakir/g') >/dev/null
done

# Agent-Config:
sudo install -m 644 \
  /opt/wakir-runtime/infra/spire/agent/config/spire-agent-wakir.conf \
  /etc/wakir/spire-agent-wakir.conf

sudo systemctl daemon-reload
sudo systemctl start wakir-spire-agent-wakir.service
```

**Verifikation:**

```bash
systemctl status wakir-spire-agent-wakir.service
# Erwartet: Active: active (running)

# SVID-Roundtrip-Verify: Workload-API ist erreichbar:
sudo podman exec wakir-spire-agent-wakir \
  /opt/spire/bin/spire-agent api fetch x509 \
    -socketPath /run/spire/agent-sockets/api.sock
# Erwartet: ein gueltiges X.509-SVID-Bundle (Subject mit SPIFFE-ID
#   spiffe://wakir.test/...) ODER Fehler "no identity issued"
#   falls noch kein Workload-Entry registriert ist (das ist ok auf
#   Erst-Bring-up; wir registrieren in Schritt 4.5 einen Test-
#   Workload).
```

### 4.4 NATS-JetStream-Container

```bash
sudo install -m 644 /opt/wakir-runtime/quadlet/wakir-nats.container \
  /etc/containers/systemd/wakir-nats.container

sudo systemctl daemon-reload
sudo systemctl start wakir-nats.service
```

**Verifikation:**

```bash
systemctl status wakir-nats.service
# Erwartet: Active: active (running)

sudo podman healthcheck run wakir-nats
# Erwartet: exit 0

curl -s http://127.0.0.1:8222/jsz | jq -r '.streams'
# Erwartet: 0 (frisches JetStream, noch keine Streams)
```

### 4.5 Test-Workload-Entry + SVID-Roundtrip-Verify

Bevor wir den NATS-KV-Bucket-Provisioner starten, validieren wir
dass der SPIRE-Agent fuer einen Test-Workload eine SVID ausstellt
(End-to-End-Identity-Pfad funktioniert).

```bash
# Test-Workload-Entry registrieren:
sudo podman exec wakir-spire-server-federation-wakir \
  /opt/spire/bin/spire-server entry create \
    -parentID spiffe://wakir.test/spire/agent/x509pop/$(hostname -s) \
    -spiffeID spiffe://wakir.test/workload/test \
    -selector unix:uid:1000 \
    -ttl 600

# SVID fetchen (auf der Agent-Sockel):
sudo podman exec wakir-spire-agent-wakir \
  /opt/spire/bin/spire-agent api fetch x509 \
    -socketPath /run/spire/agent-sockets/api.sock
```

**Erwartet:** ein gueltiges X.509-SVID mit Subject-Alternative-Name
`URI:spiffe://wakir.test/workload/test`. Falls "no identity issued"
zurueckkommt: in §7 dokumentierter Rollback-Pfad.

**Snapshot:**

```bash
# Auf dem Proxmox-Host:
qm snapshot 101 post-spire --description "SPIRE-SVID-Roundtrip ok"
```

## 5. NATS-KV-Bucket-Init (Pilot-Org acme)

Der Sprint-9-Tag-1 One-Shot-Provisioner legt pro Org einen
Marker-Stack-Bucket an.

### 5.1 Onboarded-Orgs-Roster

```bash
sudo install -d -m 755 /etc/wakir
sudo tee /etc/wakir/onboarded-orgs > /dev/null <<'EOF'
# Wakir Phase-1b Single-Org-Pilot — onboarded organisations
acme
EOF

sudo install -m 600 /dev/null /etc/wakir/nats-kv-bucket-init.env
sudo tee /etc/wakir/nats-kv-bucket-init.env > /dev/null <<'EOF'
# Phase-1b: open-token, kein Auth-Token. Phase-3: SPIFFE-JWT-SVID.
WAKIR_NATS_TOKEN=
EOF
```

### 5.2 Provisioner-Unit installieren + starten

```bash
sudo install -m 644 /opt/wakir-runtime/quadlet/wakir-nats-kv-bucket-init.container \
  /etc/containers/systemd/wakir-nats-kv-bucket-init.container
sudo systemctl daemon-reload
sudo systemctl start wakir-nats-kv-bucket-init.service
```

**Verifikation:**

```bash
journalctl -u wakir-nats-kv-bucket-init.service --since '5 min ago' \
  | tail -20
# Erwartet (Auszug):
#   [nats-kv-bucket-provision] org=acme bucket=wakir-marker-stack-acme: created  (Wirelang persistent marker-stack event log (Phase-2))
#   {"actions":[{"bucket":"wakir-marker-stack-acme","detail":"...","drift":{},"org_id":"acme","status":"created"}],"dry_run":false,"servers":"nats://wakir-nats:4222","summary":{"created":1,"drift":0,"total":1,"unchanged":0,"would_create":0}}
#   wakir-nats-kv-bucket-init.service: Deactivated successfully.

# Cross-Check via NATS-CLI (optional):
sudo podman run --rm --network wakir-orchestrator \
  docker.io/natsio/nats-box:latest \
  nats kv ls --server nats://wakir-nats:4222
# Erwartet: wakir-marker-stack-acme  (und ggf. die Phase-1b
#   Sieben-Bucket-Inventar, falls init-nats-buckets.py vorher lief)
```

### 5.3 Idempotenz validieren

Re-Start des One-Shots MUSS no-op-en:

```bash
sudo systemctl start wakir-nats-kv-bucket-init.service
journalctl -u wakir-nats-kv-bucket-init.service --since '1 min ago' \
  | grep nats-kv-bucket-provision
# Erwartet:
#   [nats-kv-bucket-provision] org=acme bucket=wakir-marker-stack-acme: unchanged
```

**Snapshot:**

```bash
# Auf dem Proxmox-Host:
qm snapshot 101 post-bucket-init --description "Marker-Stack-Bucket-acme ok"
```

## 6. Smoke-Test mit `bin/proxmox-bringup-smoke`

Letzte Verifikation: das gepackte Smoke-Skript laeuft alle
Acceptance-Checks in einem Rutsch.

```bash
sudo /opt/wakir-runtime/bin/proxmox-bringup-smoke --org acme
# Erwartet: alle Checks "PASS", exit 0.
#
# Output-Format (eine Zeile pro Check):
#   [bringup-smoke] quadlet-units-active          PASS
#   [bringup-smoke] nats-jetstream-reachable      PASS
#   [bringup-smoke] spire-server-healthy          PASS
#   [bringup-smoke] spire-agent-healthy           PASS
#   [bringup-smoke] spire-workload-api-reachable  PASS
#   [bringup-smoke] marker-stack-bucket-present   PASS
#   [bringup-smoke] SUMMARY: 6/6 checks PASS
```

Bei einem `FAIL`: §7 Rollback und Bug-Report an Kai (Outbox-
Rapport-Pfad).

**Snapshot:**

```bash
# Auf dem Proxmox-Host:
qm snapshot 101 post-bring-up-clean --description "Bring-up vollstaendig, Smoke ok"
```

## 7. Rollback-Pfad

Jeder Schritt oben hat einen Pre-Snapshot. Bei Fehler:

```bash
# Auf dem Proxmox-Host:
qm rollback 101 <snapshot-name>
# z.B. qm rollback 101 post-image-pin  # zurueck vor Quadlet-Install
qm start 101
```

**Snapshot-Kette (von neu nach alt):**

1. `post-bring-up-clean` — Smoke-Test ok, Phase-1b-Pilot ready.
2. `post-bucket-init` — NATS-KV-Bucket-acme angelegt.
3. `post-spire` — SVID-Roundtrip verifiziert.
4. `post-image-pin` — Cosign-Pin-Resolve abgeschlossen.
5. `pre-bring-up` — frische VM, vor Repo-Klon.

**Vollstaendiger Reset:** `qm rollback 101 pre-bring-up` setzt
die VM auf den frischen OS-Install zurueck.

## 8. Was Phase-1b-Pilot NICHT abdeckt

- **Kein Phase-3a-Production-Trust-Domain.** Wir bleiben auf
  `wakir.test`. Live-`<FTD-ID>.wakir.dev` ist Sprint-10+-Thema.
- **Kein Multi-Org-Federation in diesem Recipe.** Single-Org-
  Pilot mit `acme`-Bucket. Der zweite Pilot-Org-Onboard
  (`partner.test`-Spiegel) ist in `MULTI_ORG_ONBOARDING_RECIPE.md`
  (Sprint-9 Tag-2) als Erweiterung dokumentiert; die Quadlet-
  Substrate dafuer existiert bereits unter
  `infra/spire/federation/quadlet/` (per-side Templates).
- **Kein SPIFFE-JWT-SVID-NATS-Auth.** Phase-1b NATS laeuft offen
  (loopback-only); Token-Auth ist Phase-2.4-Substrate. Phase-3
  promotes auf SPIFFE-JWT-SVID-Workload-Identity.
- **Kein Cosign-Pin auf den Pilot-Provisioner-Container** ueber
  Tag hinaus — der python:3.13-slim-Pin lebt im selben Cross-
  Review-Workflow wie die SPIRE-Server/Agent-Pins, aber kein
  zweiter Verifikations-Layer.
- **Kein TEE-Attestation** (V-904 Phase-3-Substrate); Pilot-VM
  laeuft als regulaere KVM-Guest auf Proxmox.

## 9. Anbindung an die Hermetische Substrate

Das hermetische Test-Substrate (Compose unter
`infra/spire/federation/compose/spire-federation.yaml`) bleibt
unveraendert — es ist die sandbox-sichere Form der gleichen
Quadlet-Units, die wir hier auf der Pilot-VM installieren.
Drift zwischen Compose und Quadlet ist durch
`tests/orchestrator/test_quadlet_*.py` byte-precision-getestet;
wenn die Pilot-VM gegen ein Compose-Update aus der Sandbox
driftet, schlaegt der Test fehl bevor das Update auf die VM
ausgerollt wird.

## 10. Kontakt + Cross-Review-Trail

| Zone | Counterparty | Was |
|---|---|---|
| Zone A | Reza (Wirelang) | SPIFFE-Trust-Domain-Literal (wakir.test ok, wakir.dev Phase-3) |
| Zone B | Reza (NATS-Schema) | per-org `wakir-marker-stack-{org_id}` Bucket-Family (Sprint-8 Tag-4 owner) |
| Zone C | Tomás (OTS / Image-Pipeline) | Cosign-Pin-Resolve fuer SPIRE-Server/Agent + python:3.13-slim |
| Zone D | Reza (V-904 Identity-Bridge) | nicht in Pilot-Scope (Phase-3) |

Aisha protokolliert Konsens-Zeitpunkte. Bei Bring-up-Block:
Spawn-Return mit Diagnose an Kai (Outbox-Rapport-Pfad).

— Kai
