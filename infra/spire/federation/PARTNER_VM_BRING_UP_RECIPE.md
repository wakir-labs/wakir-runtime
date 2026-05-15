<!--
SPDX-License-Identifier: CC-BY-4.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Partner-VM Bring-up-Recipe — Sprint-10 Cross-VM Federation Trial

Status: Phase-2 Sprint-10 Tag-1 (Cross-VM Federation Live Trial). Operator-
Hand-Pfad fuer den Aufsichtsrat-Bring-up der ZWEITEN Proxmox-VM als
Federation-Partner-Side. Sandbox-Boundary: dieses Dokument beschreibt
was der Operator (Fred) auf dem Proxmox-Host tut; die Sandbox fuehrt
keinen Live-Bring-up aus (`feedback_sandbox_host_trennung.md`).

**Dogfood-First-Posture (AR-Decision 2026-05-14 19:30 CEST):** das
M-3 Live-Federation-Trial-Gate aus Sprint-7-Closeout §7 wird mit einer
**zweiten Proxmox-VM** umgesetzt, nicht mit einem externen Partner.
Beide VMs laufen auf demselben Proxmox-Host, sind ueber eine interne
Proxmox-Bridge gekoppelt, und gehoeren vollstaendig der Wakir-
Operation. Externe Partner-Federation ist Phase-3+ und nicht Thema
dieses Recipes.

Companion-Artefakte:

- `PROXMOX_BRING_UP_RECIPE.md` — die Wakir-Side-Recipe (Sprint-9 Tag-1
  Baseline). Dieses Recipe ist der **Spiegel** der Wakir-Side mit
  Side=orbit. Lies das Wakir-Side-Recipe zuerst, dann hier den Diff.
- `wakir-pilot-bootstrap.sh` (Sprint-10-Tag-1 patched) — der One-Shot-
  Bootstrap-Skript, jetzt `WAKIR_SIDE=orbit`-aware.
- `proxmox-bringup-smoke` (Sprint-10-Tag-1 patched) — `--side` +
  `--peer-side` parametrisiert.
- `config/spire-server-orbit.conf` + `config/spire-agent-orbit.conf`
  (NEU) — die Orbit-Side-Configs fuer das Federation-Peering.
- `bin/wakir-quadlet-lint.sh` (Sprint-10-Tag-1 patched) — lintet jetzt
  drei Sides (wakir, partner, orbit).

Lesepfad: dieser Recipe-Text ist **sequenziell**. Jeder Schritt
schliesst mit einer Verifikation; jede Verifikation hat einen
erwarteten Output. Bei einem Mismatch: VM-Snapshot zurueckrollen
(§8), nicht weiterklicken.

## 0. Was hier passiert (Ueberblick)

Wir bringen auf demselben Proxmox-Host eine ZWEITE VM hoch (die
"Partner-VM", Trust-Domain `orbit.test`), parallel zur bereits
laufenden Wakir-VM (Trust-Domain `wakir.test`). Auf der Orbit-VM
laufen die GLEICHEN vier Container-Workloads wie auf der Wakir-VM:

1. **NATS-JetStream** (`wakir-nats`) — der Phase-1b Message-Bus.
2. **SPIRE-Server-Federation** (`wakir-spire-server-federation-orbit`)
   — der Workload-Identity-Aussteller fuer die `orbit.test`
   Trust-Domain.
3. **SPIRE-Agent-Federation** (`wakir-spire-agent-orbit`) — der
   Agent-Sidecar, der Workload-API-Sockets bereitstellt.
4. **NATS-KV-Bucket-Init** (`wakir-nats-kv-bucket-init`) — der
   One-Shot-Provisioner, der pro Org den Marker-Stack-Bucket anlegt.

Zusaetzlich konfigurieren wir BEIDE VMs (Wakir + Orbit) so dass sie
sich gegenseitig **federieren koennen**:

- Jede VM kennt eine `/etc/hosts`-Eintrag fuer den jeweils anderen
  Bundle-Endpoint (`spire-server-wakir` -> Wakir-VM-IP, `spire-server-
  orbit` -> Orbit-VM-IP).
- Beide SPIRE-Server haben einen `federates_with`-Block auf den
  jeweils anderen Trust-Domain-Endpoint.
- Beide SPIRE-Server publizieren ihren Bundle-Endpoint auf Port 8443
  des `wakir-federation`-Bridges.

### Trust-Domain-Naming (AR-Decision-Slot 2026-05-15)

Wir nutzen folgende Default-Variante (Variante-C aus Mira-Empfehlung
2026-05-14 19:30 CEST):

| Side | Trust-Domain | VM-Hostname | Bridge-IP (default) |
|---|---|---|---|
| Wakir-Side | `wakir.test` | `wakir-pilot` | `10.0.42.10` |
| Orbit-Side | `orbit.test` | `wakir-orbit-pilot` | `10.0.42.11` |

**Variantenraum (AR-Decision-Slot morgen):**

| Variante | Wakir-Side | Orbit-Side | Bemerkung |
|---|---|---|---|
| A | `wakir.test` | `wakir.test-orbit` | Sub-Domain-Pattern; unueblich fuer SPIFFE-Trust-Domains. |
| B | `acme.wakir` | `orbit.wakir` | Org-Slug-Pattern; bricht die RFC-6761-`.test`-Reservierung. |
| **C** (Default) | `wakir.test` | `orbit.test` | Trust-Domain-pro-VM, gleiche RFC-6761-`.test`-Reservierung. |

**Empfehlung Variante C** (begruendet in `spire-server-orbit.conf`-
Header): symmetrische Mirror-Form, kein Sub-Domain-Bias, behaelt
RFC-6761-Hygiene. Die Wakir-Side bleibt unveraendert auf `wakir.test`.

Phase-3a-Production-Trust-Domain (`<FTD-ID>.wakir.dev` jeweils) ist
**explizit nicht Thema** dieses Recipes — Live-DNS, Production-CA,
und Trust-Domain-Migration sind Sprint-12+-Items.

### Sandbox vs. Operator-Hand-Grenze

| Phase | Wer | Wo |
|---|---|---|
| Spec/Code-Bauen | Sandbox (Kai, Reza, Tomás) | wakir-runtime-Repo, hermetische Tests |
| Image-Pin-Aufloesung | Operator-Hand (Tomás Cross-Review) | `cosign verify` auf Host |
| VM-Erstellung (Orbit-VM) | Operator-Hand (Fred) | Proxmox-Web-UI / qm-CLI |
| Cross-VM-Bridge-Setup | Operator-Hand (Fred) | Proxmox-Web-UI (vmbr1) |
| Quadlet-Install | Operator-Hand (Fred) | SSH auf Orbit-VM, `WAKIR_SIDE=orbit` |
| Federation-Bundle-Sync | Operator-Hand (Fred) | initial Bundle-Exchange via spire-fed-bundle CLI |
| Smoke-Verify | Operator-Hand (Fred) | `proxmox-bringup-smoke --side orbit --peer-side wakir` |
| Rollback | Operator-Hand (Fred) | Proxmox-Web-UI, VM-Snapshot |

## 1. Voraussetzung: Wakir-Side-VM steht

Bevor die Orbit-VM hochgebracht wird, MUSS die Wakir-Side-VM den
Sprint-9-Tag-9-Smoke vollstaendig bestehen:

```bash
# Auf der Wakir-VM:
sudo /opt/wakir-runtime/bin/proxmox-bringup-smoke --org acme
# Erwartet: SUMMARY: 6/6 checks PASS
```

Falls die Wakir-Side-Smoke nicht 6/6 ist: erst die Wakir-Side
fix-en (PROXMOX_BRING_UP_RECIPE.md §7 Rollback), DANN dieses Recipe
starten. Federation-Bring-up auf einem broken Wakir-Substrate ist
sinnlos.

## 2. Cross-VM-Bridge-Setup (Proxmox-Host)

Wir richten eine dedizierte Proxmox-internal Bridge ein, die nur die
Wakir-VM und die Orbit-VM verbindet. Kein externes Routing.

### 2.1 Bridge vmbr1 anlegen

Auf dem Proxmox-Host (nicht in einer VM!):

```bash
# Proxmox-Web-UI: Datacenter > <host> > Network > Create > Linux Bridge
# Name:        vmbr1
# Subnet:      10.0.42.0/24
# Gateway:     (leer, kein Routing nach extern)
# Comment:     wakir-federation-internal
# Autostart:   yes
# VLAN aware:  no

# Oder per CLI in /etc/network/interfaces.d/vmbr1.cfg:
sudo tee /etc/network/interfaces.d/vmbr1.cfg <<'EOF'
auto vmbr1
iface vmbr1 inet manual
    bridge-ports none
    bridge-stp off
    bridge-fd 0
    bridge-vlan-aware no
    # wakir-federation-internal — Cross-VM Federation bridge,
    # subnet 10.0.42.0/24, no external routing.
EOF

sudo systemctl reload networking
ip link show vmbr1
# Erwartet: vmbr1 is UP
```

### 2.2 Wakir-VM um zweite NIC erweitern

Die existierende Wakir-VM hat aktuell nur `vmbr0` (externes
Routing). Wir haengen einen zweiten Netzwerk-Adapter an:

```bash
# Auf dem Proxmox-Host:
WAKIR_VMID=101    # bestehende Wakir-VM
qm set $WAKIR_VMID --net1 virtio,bridge=vmbr1
# Erwartet: update VM 101: -net1 virtio,bridge=vmbr1
```

In der Wakir-VM die neue NIC konfigurieren (statisch 10.0.42.10):

```bash
# In der Wakir-VM (via SSH):
sudo nmcli connection add type ethernet \
  con-name wakir-federation \
  ifname ens19 \
  ip4 10.0.42.10/24
sudo nmcli connection up wakir-federation
ip addr show ens19
# Erwartet: inet 10.0.42.10/24
```

(Hinweis: NIC-Name `ens19` ist Fedora-CoreOS-Default fuer die zweite
virtio-NIC. Auf Debian-12 kann es `enp19s0` oder `eth1` sein —
`ip link show` listet die tatsaechliche NIC-ID.)

## 3. Orbit-VM erstellen

### 3.1 VM-Spec-Empfehlung

Spiegel der Wakir-VM-Spec (PROXMOX_BRING_UP_RECIPE.md §1.1):

| Resource | Empfehlung | Begruendung |
|---|---|---|
| OS | Fedora-CoreOS 40+ (stable) | Quadlet-Parity mit Wakir-VM |
| vCPU | 4 cores | gleiche Workloads |
| RAM | 4 GiB | gleiche Workloads |
| Disk | 32 GiB (thin-provisioned) | gleiche Workloads |
| Netzwerk | 2 NICs: vmbr0 (extern), vmbr1 (10.0.42.0/24) | Federation-Bridge |
| Snapshot | aktiviert | jeder Schritt unten endet mit Snapshot-Empfehlung |

### 3.2 VM-Erstellung

Auf dem Proxmox-Host:

```bash
ORBIT_VMID=102    # neue Orbit-VM
STORAGE=local-lvm
ISO=fedora-coreos-40-stable.iso

qm create $ORBIT_VMID \
  --name wakir-orbit-pilot \
  --memory 4096 \
  --cores 4 \
  --net0 virtio,bridge=vmbr0 \
  --net1 virtio,bridge=vmbr1 \
  --scsihw virtio-scsi-single \
  --scsi0 $STORAGE:32 \
  --cdrom local:iso/$ISO \
  --boot c --bootdisk scsi0 \
  --ostype l26 \
  --agent enabled=1

qm start $ORBIT_VMID
# Konsole oeffnen + Fedora-CoreOS installieren.
```

**Verifikation:**

```bash
qm status $ORBIT_VMID
# Erwartet: status: running
```

### 3.3 Federation-NIC auf Orbit-VM konfigurieren

In der Orbit-VM via SSH:

```bash
sudo nmcli connection add type ethernet \
  con-name wakir-federation \
  ifname ens19 \
  ip4 10.0.42.11/24
sudo nmcli connection up wakir-federation
ip addr show ens19
# Erwartet: inet 10.0.42.11/24
```

### 3.4 Cross-VM-DNS via /etc/hosts

Auf der **Wakir-VM** (rueckwirkend):

```bash
sudo tee -a /etc/hosts <<'EOF'
# Sprint-10-Tag-1 Cross-VM Federation peer (Orbit-Side)
10.0.42.11   spire-server-orbit  wakir-orbit-pilot
EOF
```

Auf der **Orbit-VM**:

```bash
sudo tee -a /etc/hosts <<'EOF'
# Sprint-10-Tag-1 Cross-VM Federation peer (Wakir-Side)
10.0.42.10   spire-server-wakir  wakir-pilot
EOF
```

**Verifikation (auf beiden VMs):**

```bash
# Von Wakir-VM:
ping -c 2 spire-server-orbit
# Erwartet: 2 packets transmitted, 2 received

# Von Orbit-VM:
ping -c 2 spire-server-wakir
# Erwartet: 2 packets transmitted, 2 received
```

**Snapshot:**

```bash
# Auf dem Proxmox-Host:
qm snapshot 102 pre-bring-up --description "Orbit-VM frisch, NICs + DNS OK"
```

## 4. Repo-Klon + Image-Pin-Resolve (Orbit-VM)

Identisch zur Wakir-Side-Recipe §2 + §3. Kurzform:

```bash
# In der Orbit-VM:
sudo mkdir -p /opt
sudo git clone https://github.com/wakir-labs/wakir-runtime.git /opt/wakir-runtime

# Cosign-Verify + Skopeo-Cross-Check (Cross-Review Zone-C, Tomás-Track):
sudo dnf install -y cosign skopeo jq
cosign verify \
  --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  ghcr.io/spiffe/spire-server:1.14.6

cosign verify \
  --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
  --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
  ghcr.io/spiffe/spire-agent:1.14.6

# Pins aufloesen:
sudo /opt/wakir-runtime/infra/spire/federation/proxmox/resolve-image-pins.sh \
  --spire-server-digest sha256:<aus-cosign> \
  --spire-agent-digest sha256:<aus-cosign> \
  --python-digest sha256:<aus-cosign-fuer-python:3.13-slim> \
  --apply

# Verifikation: keine Platzhalter mehr.
grep -rn DIGEST_PENDING_TOMAS_REVIEW /opt/wakir-runtime/quadlet/ \
  /opt/wakir-runtime/infra/spire/
# Erwartet: keine Treffer.
```

**Snapshot:**

```bash
qm snapshot 102 post-image-pin --description "Cosign-Pin-Resolve abgeschlossen"
```

## 5. Quadlet-Install mit `WAKIR_SIDE=orbit`

Hier ist der entscheidende **Diff zur Wakir-Side**: Wir setzen die
`WAKIR_SIDE`-Env-Var auf `orbit`. Der Bootstrap-Skript erledigt
dann automatisch:

- Quadlet-Container-Name `wakir-spire-server-federation-orbit`
  (statt `-wakir`).
- Config-File-Selection `spire-server-orbit.conf` + `spire-agent-
  orbit.conf` (statt der wakir-Versionen).
- Network-Alias `spire-server-orbit` (statt `spire-server-wakir`).
- Trust-Domain-Substitution `orbit.test` (auto-sync mit
  `WAKIR_SIDE`, siehe Bootstrap-Header).
- **(NEU, Sprint-10 Tag-3)** Bundle-Endpoint-Host-Bind auf `0.0.0.0`
  (statt `127.0.0.1`) wenn `WAKIR_PILOT_MODE=federation`. Das ist die
  substantielle Voraussetzung dass der peer-VM den Bundle-Endpoint
  ueberhaupt erreichen kann. Single-Org-Mode bleibt loopback-only.
  gRPC-API-Port 8081 bleibt in beiden Modi loopback-only (Security-
  Invariant — privilegierte Control-Plane).
- **(NEU, Sprint-10 Tag-3)** `WAKIR_PEER_SIDE` + `WAKIR_PEER_HOST`
  Env-Vars: setzen + die `/etc/hosts`-Entry fuer die Peer-VM wird
  automatisch installiert. Ohne diese Vars: Operator-Hand-Edit von
  `/etc/hosts` (siehe §5.2 unten).

### 5.1 Bootstrap-Skript mit WAKIR_SIDE starten

**Empfohlene Variante (Sprint-10 Tag-3, Cross-VM auto-wired):**

```bash
# In der Orbit-VM (Beispiel: wakir-pilot ist auf 192.168.178.116):
sudo env \
  WAKIR_SIDE=orbit \
  WAKIR_PILOT_MODE=federation \
  WAKIR_PEER_SIDE=wakir \
  WAKIR_PEER_HOST=192.168.178.116 \
  WAKIR_ORG_ID=acme \
  bash /opt/wakir-runtime/infra/spire/federation/wakir-pilot-bootstrap.sh
# Erwartet: 8 Schritte gruen, Final-Smoke 6/6.
#
# Bonus: das Bootstrap installiert beim Schritt 6 automatisch eine
# /etc/hosts-Entry: "192.168.178.116  spire-server-wakir".
# Der HTTPS-Endpoint des wakir-VM wird damit cross-VM erreichbar.
```

**Klassische Variante (vor Sprint-10 Tag-3, `/etc/hosts` per Hand):**

```bash
sudo env \
  WAKIR_SIDE=orbit \
  WAKIR_PILOT_MODE=federation \
  WAKIR_ORG_ID=acme \
  bash /opt/wakir-runtime/infra/spire/federation/wakir-pilot-bootstrap.sh

# Dann Operator-Hand: /etc/hosts editieren, eine Zeile:
#   192.168.178.116  spire-server-wakir
# (Ersetze die IP durch den tatsaechlichen Peer-VM-Endpoint.)
```

**Hinweis:** `WAKIR_PILOT_MODE=federation` ist die Wahl die den
Bootstrap die Federation-Configs installieren laesst (statt der
Single-Org-Pilot-Configs). Beide VMs MUESSEN `federation`-Mode
verwenden, sonst startet der SPIRE-Server nicht (Bug 7 H1, Sprint-9
Tag-5).

### 5.2 Verifikation

```bash
systemctl status wakir-spire-server-federation-orbit.service
# Erwartet: Active: active (running)

systemctl status wakir-spire-agent-orbit.service
# Erwartet: Active: active (running)

sudo podman exec wakir-spire-server-federation-orbit \
  /opt/spire/bin/spire-server healthcheck
# Erwartet: "Server is healthy."
```

**Snapshot:**

```bash
qm snapshot 102 post-spire --description "Orbit-Side SPIRE-Stack laeuft"
```

### 5.3 Wakir-Side: Federation-Mode aktivieren (rueckwirkend)

Falls die Wakir-Side aktuell im `single-org`-Mode laeuft (Sprint-9-
Tag-1-Baseline), muss sie auf `federation`-Mode umgestellt werden,
damit der `federates_with "orbit.test"`-Block aktiv ist UND der
Bundle-Endpoint-Host-Bind von `127.0.0.1` auf `0.0.0.0` flippt. Auf
der Wakir-VM:

```bash
# Stoppen + neu konfigurieren:
sudo systemctl stop wakir-spire-agent-wakir.service
sudo systemctl stop wakir-spire-server-federation-wakir.service

# Bootstrap mit federation-mode neu laufen lassen (Schritt 6 nur):
sudo env \
  WAKIR_SIDE=wakir \
  WAKIR_PILOT_MODE=federation \
  WAKIR_PEER_SIDE=orbit \
  WAKIR_PEER_HOST=192.168.178.191 \
  WAKIR_ORG_ID=acme \
  bash /opt/wakir-runtime/infra/spire/federation/wakir-pilot-bootstrap.sh \
    --resume-from 6

# Restart:
sudo systemctl start wakir-spire-server-federation-wakir.service
sudo systemctl start wakir-spire-agent-wakir.service
```

**Sprint-10 Tag-3 Effect-Check:** Nach dem `federation`-Mode-Switch
MUSS der Bundle-Endpoint auf `0.0.0.0` binden, nicht mehr auf
`127.0.0.1`. Verifikation:

```bash
sudo ss -tlnp | grep -E ':8443'
# Erwartet: LISTEN 0.0.0.0:8443 (statt 127.0.0.1:8443)

sudo cat /etc/containers/systemd/wakir-spire-server-federation-wakir.container \
  | grep -E '^PublishPort='
# Erwartet:
#   PublishPort=0.0.0.0:8443:8443       <-- Bundle-Endpoint, cross-VM
#   PublishPort=127.0.0.1:8082:8081     <-- gRPC, loopback-only (Security)
```

**Wichtig:** Die Wakir-Side-Config `spire-server-wakir.conf` enthaelt
einen `federates_with "partner.test"`-Block (Sprint-8 Tag-1 same-host
hermetic peer). Fuer das Sprint-10 Cross-VM-Setup MUSS dieser Block
auf `orbit.test` zeigen. Edit von Hand oder kuenftiger Bootstrap-
Switch — siehe §10 Open-Items.

## 6. Federation-Bundle-Sync (initial Bundle-Exchange)

Der erste Bundle-Exchange ist **Operator-Hand**. Der SPIRE-Server hat
beim ersten Start KEIN peer-Trust-Bundle und kann daher den peer's
Bundle-Endpoint nicht via SPIFFE-X.509-Auth aufrufen (Henne-Ei-
Problem des `https_spiffe`-Profils). Wir muessen den ersten Bundle-
Round-Trip per CLI seed-en.

### 6.1 Wakir-Side: Bundle exportieren

```bash
# Auf der Wakir-VM:
sudo podman exec wakir-spire-server-federation-wakir \
  /opt/spire/bin/spire-server bundle show -format spiffe \
    > /tmp/wakir-bundle.jwks

# Verifikation: JWKS-format JSON.
jq '.keys | length' /tmp/wakir-bundle.jwks
# Erwartet: >= 1 (mindestens ein Key)
```

### 6.2 Wakir-Side: Bundle nach Orbit-VM kopieren

```bash
# Auf der Wakir-VM:
scp /tmp/wakir-bundle.jwks core@10.0.42.11:/tmp/wakir-bundle.jwks
```

### 6.3 Orbit-Side: Wakir-Bundle als Federated-Bundle einspielen

```bash
# Auf der Orbit-VM:
sudo podman exec -i wakir-spire-server-federation-orbit \
  /opt/spire/bin/spire-server bundle set \
    -id spiffe://wakir.test \
    -format spiffe \
    < /tmp/wakir-bundle.jwks

# Verifikation:
sudo podman exec wakir-spire-server-federation-orbit \
  /opt/spire/bin/spire-server bundle list -format pem \
    | grep -E "Trust Domain[[:space:]]*:[[:space:]]*wakir.test"
# Erwartet: ein Treffer
```

### 6.4 Spiegel-Schritt: Orbit-Bundle exportieren + auf Wakir-VM einspielen

```bash
# Auf der Orbit-VM:
sudo podman exec wakir-spire-server-federation-orbit \
  /opt/spire/bin/spire-server bundle show -format spiffe \
    > /tmp/orbit-bundle.jwks
scp /tmp/orbit-bundle.jwks core@10.0.42.10:/tmp/orbit-bundle.jwks

# Auf der Wakir-VM:
sudo podman exec -i wakir-spire-server-federation-wakir \
  /opt/spire/bin/spire-server bundle set \
    -id spiffe://orbit.test \
    -format spiffe \
    < /tmp/orbit-bundle.jwks

# Verifikation auf der Wakir-VM:
sudo podman exec wakir-spire-server-federation-wakir \
  /opt/spire/bin/spire-server bundle list -format pem \
    | grep -E "Trust Domain[[:space:]]*:[[:space:]]*orbit.test"
# Erwartet: ein Treffer
```

Nach diesem Schritt haben beide SPIRE-Server das Peer-Bundle gecacht
und koennen die laufende Bundle-Rotation via Federation-Endpoint
selbst durchziehen.

**Snapshot:**

```bash
qm snapshot 101 post-bundle-sync --description "Wakir hat orbit.test-Bundle gecacht"
qm snapshot 102 post-bundle-sync --description "Orbit hat wakir.test-Bundle gecacht"
```

## 7. Federation-Smoke-Acceptance (NEU, Sprint-10 Tag-1)

Der `proxmox-bringup-smoke`-Skript wurde fuer Sprint-10 erweitert
mit zwei Cross-VM-Checks:

- `federation-bundle-sync-reachable` — HTTPS-GET gegen Peer-Endpoint.
- `federation-cross-trust-domain-verify` — `spire-server bundle list`
  enthaelt Peer-Trust-Domain.

Beide laufen nur wenn `WAKIR_FEDERATION_MODE=enabled` env-var gesetzt
ist — sonst werden sie als `SKIP` gemeldet.

### 7.1 Smoke auf Orbit-Side mit Federation-Checks

```bash
# Auf der Orbit-VM:
sudo env \
  WAKIR_FEDERATION_MODE=enabled \
  /opt/wakir-runtime/bin/proxmox-bringup-smoke \
    --org acme \
    --side orbit \
    --peer-side wakir
# Erwartet:
#   [bringup-smoke] quadlet-units-active             PASS
#   [bringup-smoke] nats-jetstream-reachable         PASS
#   [bringup-smoke] spire-server-healthy             PASS
#   [bringup-smoke] spire-agent-healthy              PASS
#   [bringup-smoke] spire-workload-api-reachable     PASS
#   [bringup-smoke] marker-stack-bucket-present      PASS
#   [bringup-smoke] federation-bundle-sync-reachable PASS
#   [bringup-smoke] federation-cross-trust-domain-verify PASS
#   [bringup-smoke] SUMMARY: 8/8 checks PASS
```

### 7.2 Smoke auf Wakir-Side mit Federation-Checks

```bash
# Auf der Wakir-VM:
sudo env \
  WAKIR_FEDERATION_MODE=enabled \
  /opt/wakir-runtime/bin/proxmox-bringup-smoke \
    --org acme \
    --side wakir \
    --peer-side orbit
# Erwartet: 8/8 checks PASS
```

Wenn BEIDE Sides 8/8 melden: M-3 Live-Federation-Trial-Gate ist
strukturell **vollstaendig geschlossen**. Sprint-7-Closeout §7 ist
formal abschluss-faehig; Phase-2 ist eroffnungs-faehig.

**Snapshot:**

```bash
qm snapshot 101 post-fed-smoke-clean --description "Wakir-Side 8/8 Federation-Smoke ok"
qm snapshot 102 post-fed-smoke-clean --description "Orbit-Side 8/8 Federation-Smoke ok"
```

### 7.3 M-3 Live-Trial Validation (Mira-Hand-Pfad, Sprint-10 Tag-3)

Diese Sektion ist die explizite Sequenz die Mira nach dem Merge des
Sprint-10-Tag-3-PR auf den beiden Live-VMs ausfuehrt. Sandbox-Boundary:
Kai liefert die Substanz (Code, Configs, Tests, Recipe-Update); Mira
fuehrt den Live-Trial aus. Erfolgs-Kriterium: 8/8 PASS auf beiden
Sides + Reza's Live-HTTPS-Adapter-Test (`test_live_int_live_partner_vm`)
gruen gegen `WAKIR_LIVE_PARTNER_URL=https://wakir-orbit:8443`.

**Bootstrap-Sequenz (beide VMs, Sprint-10 Tag-3 auto-wired):**

```bash
# Schritt 1: wakir-orbit (192.168.178.191) auf federation-mode flashen.
ssh -i /home/fred/.ssh/wakir-pilot-vm-diagnose root@192.168.178.191
sudo systemctl stop wakir-spire-agent-orbit.service \
                   wakir-spire-server-federation-orbit.service
sudo env \
  WAKIR_SIDE=orbit \
  WAKIR_PILOT_MODE=federation \
  WAKIR_PEER_SIDE=wakir \
  WAKIR_PEER_HOST=192.168.178.116 \
  WAKIR_ORG_ID=acme \
  bash /opt/wakir-runtime/infra/spire/federation/wakir-pilot-bootstrap.sh \
    --resume-from 6
sudo systemctl start wakir-spire-server-federation-orbit.service
sudo systemctl start wakir-spire-agent-orbit.service

# Schritt 2: wakir-pilot (192.168.178.116) — Option B aus Auftrag:
#   wakir-pilot bleibt single-org als V2-Anchor. Kein Switch noetig.
# Falls Option A (beide federation) oder Option C (beide federation
# mit pre-snapshot-Backup) gewaehlt wird: analoger Aufruf auf
# wakir-pilot mit WAKIR_PEER_SIDE=orbit, WAKIR_PEER_HOST=192.168.178.191.

# Schritt 3: Bundle-Sync (Operator-Hand, einmalig per CLI seed):
# Folge §6 (Federation-Bundle-Sync) zwischen den beiden VMs.

# Schritt 4: Smoke-Verify auf wakir-orbit:
ssh -i /home/fred/.ssh/wakir-pilot-vm-diagnose root@192.168.178.191
sudo env \
  WAKIR_FEDERATION_MODE=enabled \
  /opt/wakir-runtime/bin/proxmox-bringup-smoke \
    --org acme \
    --side orbit \
    --peer-side wakir
# Erwartet: 8/8 checks PASS

# Schritt 5: Reza's Live-Adapter-Test (von der Sandbox, oder von
# wakir-pilot mit installiertem wirelang):
WAKIR_LIVE_PARTNER_URL=https://wakir-orbit:8443 \
  python -m pytest \
    wirelang/tests/test_spire_fed_bundle_live_https_fetcher.py::test_live_int_live_partner_vm \
    -v
# Erwartet: PASSED
```

**Bei Fehler (Bring-up bricht):** SSH-Diagnose-Pfad ist via
`/home/fred/.ssh/wakir-pilot-vm-diagnose` verfuegbar fuer beide VMs
(root@192.168.178.191 = wakir-orbit, root@192.168.178.116 = wakir-pilot).
Live-Diagnose-Logs (analog Bug-26/27/28-Pattern) sammeln, Kai fixt
source.

## 8. Rollback-Pfad

Spiegel zu Wakir-Side §7. Pro Phase ein Snapshot, im Fehlerfall
rollback und Bug-Report.

**Snapshot-Kette Orbit-VM (von neu nach alt):**

1. `post-fed-smoke-clean` — Federation-Smoke 8/8 ok.
2. `post-bundle-sync` — Wakir-Bundle in Orbit-SPIRE-Server gecacht.
3. `post-spire` — Orbit-SPIRE-Stack laeuft.
4. `post-image-pin` — Cosign-Pin-Resolve abgeschlossen.
5. `pre-bring-up` — frische Orbit-VM, NICs + Cross-VM-DNS OK.

**Vollstaendiger Reset:** `qm rollback 102 pre-bring-up` setzt die
Orbit-VM auf den frischen OS-Install zurueck (Wakir-Side bleibt
unbeeintraechtigt).

## 9. Cross-Review-Trail (Sprint-10 Tag-1)

| Zone | Counterparty | Was |
|---|---|---|
| Zone A | Reza (Wirelang) | Federation-Bundle-Endpoint-URL-Shape-Konsens mit PR #51 Adapter (Root-Path vs. ``/bundle``-Suffix) |
| Zone B | Reza (NATS-Schema) | per-org Marker-Stack-Bucket-Family bleibt unveraendert (Orbit-VM hat eigenen NATS-JetStream) |
| Zone C | Tomás (OTS / Image-Pipeline) | Quadlet-:Z-Disziplin + Image-Pin-Disziplin im neuen Orbit-Side-Set; Tag-9 SELinux-Lane + Quadlet-Lint garantieren das strukturell |
| Zone D | Reza (V-904 Identity-Bridge) | nicht in Pilot-Scope (Phase-3) |
| Zone X | Amara (QA / Mutation-Test) | Mutation-Equivalence-Job-Inventar `KNOWN_QUADLETS` erweitern um Orbit-Side-Substitution; Tag-9-Lane sollte Orbit-Stage automatisch finden (Lint-Skript wurde erweitert) |

Aisha protokolliert Konsens-Zeitpunkte. Bei Bring-up-Block: Spawn-
Return mit Diagnose an Kai (Outbox-Rapport-Pfad).

## 10. Was Sprint-10-Tag-1 NICHT abdeckt (Open-Items)

- **AR-Decision-Slot 2026-05-15 Trust-Domain-Naming:** Variante-C
  (`wakir.test` + `orbit.test`) ist Default; AR-Final-Entscheidung
  pending.
- **Bootstrap-Switch fuer rueckwirkende `federates_with`-Aenderung
  auf der Wakir-Side:** §5.3 verlangt aktuell einen Edit von Hand der
  `spire-server-wakir.conf`. Sprint-10-Tag-2+ kann das via
  `WAKIR_PEER_SIDE`-Env-Var automatisieren.
- **Reza PR #51 Adapter-URL-Shape:** Adapter pinnt
  `https://spire-server-<side>:8443/bundle`; SPIRE-Server-
  `https_spiffe`-Profil serviert den Bundle am Root-Pfad. Der Smoke
  testet beide Pfade (root + `/bundle`-Suffix) als Toleranz. Zone-A
  Konsens-Item.
- **Live-HTTPS-Cert-Validation:** der Smoke nutzt `curl -k` (cert-
  validation off) als Pragmatik gegen das `https_spiffe`-self-issued-
  Cert. Production-Posture (Phase-3a) ist `https_web` mit echtem
  WebPKI; Live-Cert-Validation kommt dann hin.
- **Kein Phala-Cloud-Backend** (V-904 Phase-3-Substrate). Orbit-VM
  laeuft als regulaere KVM-Guest auf Proxmox; TEE-Attestation ist
  Phase-3+.

## 11. Anbindung an die Hermetische Substrate

Das hermetische Test-Substrate (Compose unter
`infra/spire/federation/compose/spire-federation.yaml`) bleibt
unveraendert — es ist die same-host hermetic-Form mit `wakir.test`
+ `partner.test`. Das Sprint-10-Tag-1 Cross-VM-Setup nutzt
`wakir.test` + `orbit.test` und hat KEIN compose-Pendant — Cross-VM
ist per Definition kein same-host-compose-Scenario. Die hermetischen
Tests bleiben fuer die same-host-Posture relevant; der Cross-VM-Pfad
ist Operator-Hand-only.

Drift-Schutz:
- `tests/orchestrator/test_proxmox_bringup_smoke*.py` testet die
  Smoke-Logik fuer `--side wakir` + `--side orbit` mit Mock-Pattern.
- `infra/spire/federation/bin/wakir-quadlet-lint.sh` lintet jetzt
  drei Sides (wakir, partner, orbit) — Substitutions-Drift faengt
  schon im PR auf.
- `tests/infra/test_pilot_bootstrap_side_aware.py` (NEU,
  Sprint-10 Tag-1) testet die `WAKIR_SIDE`-Env-Var-Hygiene.

## 12. Kontakt + Eskalations-Pfad

- **Sprint-10-Tag-1-Owner:** Kai Hoffmann (DevOps), Spawn-Return mit
  Outbox-Rapport an Priya CTO + cc Mira CEO.
- **Cross-Review Zone A:** Reza (Adapter-URL-Konsistenz).
- **Cross-Review Zone C:** Tomás (Quadlet-:Z + Image-Pin-Disziplin).
- **Cross-Review Zone X:** Amara (Mutation-Test-Methodik).
- **Architecture-Frage:** Priya CTO.
- **Strategie/Naming-Frage:** Mira CEO (Trust-Domain-Naming-Final
  ist AR-Touch).

— Kai
