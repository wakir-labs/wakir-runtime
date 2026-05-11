# Quadlet / systemd Migration Skizze — alternativer Container-Lifecycle für Phase-2/3

**Status:** Skizze (design-only). Not a migration decision. Not a
Phase-2-Sprint-5 commitment to switch lifecycle managers. This document
captures the Quadlet/systemd shape so the operator-side has a
documented alternative to `docker compose` for atomic-host targets.

**Authoring context:** Phase-2 Sprint-5 Tag-4 (2026-05-11). Owner:
DevOps / Container-Orchestration side. Box: 60 min. β-push (doc).

**Cross-Review-Status:** Z-A / Z-B / Z-C / Z-D non-touched. This
skizze does not edit container identity (Z-A), NATS schema (Z-B),
image-pin pipeline (Z-C), or Phala-Cloud bridge (Z-D). It is a
lifecycle-manager-shape document with no behavior change.

---

## 1 / Why this skizze exists

### 1.1 Operator-side host-OS reality

The current operator-side host runs a Fedora-Atomic-class distribution
(Silverblue / Bluefin / Kinoite family — image-based, immutable
`/usr`, rpm-ostree-managed). Atomic hosts ship with:

- **Podman** as the container engine (no `dockerd` daemon).
- **systemd** as the only first-class service manager.
- **Quadlet** (`/etc/containers/systemd/*.container`) as the
  Podman-native systemd integration since Podman 4.4 (2023). On
  Fedora 41+ Quadlet is the recommended lifecycle path for
  long-running containers, ahead of `podman generate systemd` (which
  is deprecated as of Podman 4.6).

`docker compose` works on these hosts via `podman-compose` or
`podman compose` (compose-spec-compatible Podman frontend), but the
host-native pattern is Quadlet: a `.container` unit file is parsed
at boot by `systemd-generators` into a synthesised `.service` unit,
and the container's lifecycle is just another systemd service.

### 1.2 Brand-compliance angle

Wakir Labs' operator-side runtime baseline is atomic-distro-class
(Fedora Atomic / Bluefin). Shipping a `docker-compose.yaml` as the
only operator-facing bring-up artefact means the operator pays a
translation tax on every bring-up (compose → podman-compose → ad-hoc
service supervision). Shipping a Quadlet unit alongside the compose
file lets atomic-host operators consume the host-native pattern.

The compose file stays the **primary Phase-1b/2 contract surface**
(orchestrator-side tests assert against it; the runbook's bring-up
section uses `docker compose -f compose/nats.yaml up -d`). Quadlet
is the **alternative** for operators who prefer host-native systemd
integration.

### 1.3 What this skizze is NOT

- **Not a migration commitment.** The compose file stays. Tests
  continue to assert against `compose/nats.yaml`. No deletion of the
  compose contract.
- **Not a Phase-2 implementation.** This is design-shape only. The
  Quadlet unit body is sketched, not committed as a runnable file.
- **Not a Z-A / Z-B / Z-C / Z-D touchpoint.** No container-identity
  change, no schema change, no image-pin change, no TEE/Phala touch.
- **Not a Helm-chart replacement.** Helm/Kubernetes is the Phase-3
  cluster path (per the compose file's Box-5-Helm-chart note). Quadlet
  is the single-host atomic-distro path. Different deployment surface,
  not in competition.

---

## 2 / Quadlet shape for `compose/nats.yaml`

### 2.1 Direct translation of the NATS service

The NATS service in `compose/nats.yaml` declares (Sprint-4 Tag-3
digest-pin state, unchanged):

- Image: `nats:2.11-alpine@sha256:e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00`
- Command: `--jetstream --store_dir=/data/jetstream --http_port=8222 --name=wakir-nats-phase1`
- Ports: `127.0.0.1:4222:4222`, `127.0.0.1:8222:8222`
- Volume: `wakir-nats-jetstream-data` mounted at `/data/jetstream`
- Network: `wakir-orchestrator` (bridge)
- Restart: `unless-stopped`
- Healthcheck: `wget -q -O - http://127.0.0.1:8222/jsz >/dev/null`
- Hardening: `cap_drop: ALL`, `security_opt: no-new-privileges:true`
- Resource limits: 1.0 CPU, 512 MiB memory

Translated to a Quadlet `.container` unit (shape — not a committed
file; lives in `/etc/containers/systemd/wakir-nats.container` on the
operator host):

```ini
# /etc/containers/systemd/wakir-nats.container
# Phase-2 Quadlet skizze — host-native lifecycle for the Phase-1b
# NATS-JetStream substrate (mirror of compose/nats.yaml).
# SPDX-License-Identifier: Apache-2.0

[Unit]
Description=Wakir Phase-1b NATS-JetStream substrate
After=network-online.target
Wants=network-online.target

[Container]
ContainerName=wakir-nats
Image=docker.io/library/nats:2.11-alpine@sha256:e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00

# Command-line (mirror of compose `command:` block)
Exec=--jetstream --store_dir=/data/jetstream --http_port=8222 --name=wakir-nats-phase1

# Loopback-only port publication (mirror of compose ports:)
PublishPort=127.0.0.1:4222:4222
PublishPort=127.0.0.1:8222:8222

# JetStream persistence volume (Quadlet-managed, name-stable)
Volume=wakir-nats-jetstream-data.volume:/data/jetstream

# User-defined bridge network for orchestrator co-location
Network=wakir-orchestrator.network

# Container-init hardening (mirror of compose cap_drop + security_opt)
DropCapability=ALL
NoNewPrivileges=true

# Resource envelope (Quadlet maps cleanly to cgroup-v2 limits on
# atomic hosts; the compose `deploy.resources` block is advisory
# under compose v2 — Quadlet enforces these on Podman 4.4+)
PodmanArgs=--cpus=1.0 --memory=512m

# Health probe (Quadlet defers to Podman's --health-* flags)
HealthCmd=wget -q -O - http://127.0.0.1:8222/jsz >/dev/null 2>&1 || exit 1
HealthInterval=10s
HealthTimeout=3s
HealthRetries=5
HealthStartPeriod=5s

[Service]
# Mirror of compose `restart: unless-stopped`
Restart=on-failure
RestartSec=5s
TimeoutStartSec=120s

[Install]
WantedBy=multi-user.target default.target
```

Plus the network and volume sidecar units (Quadlet requires
explicit `.network` and `.volume` units for non-default resources):

```ini
# /etc/containers/systemd/wakir-orchestrator.network
[Unit]
Description=Wakir orchestrator bridge network

[Network]
NetworkName=wakir-orchestrator
Driver=bridge
```

```ini
# /etc/containers/systemd/wakir-nats-jetstream-data.volume
[Unit]
Description=Wakir NATS JetStream persistence volume

[Volume]
VolumeName=wakir-nats-jetstream-data
```

### 2.2 Operator bring-up flow (Quadlet path)

```bash
# One-time install — copy the three unit files into the systemd
# search path. On rootful Podman use /etc/containers/systemd/;
# on rootless Podman use ~/.config/containers/systemd/.
sudo install -m 644 wakir-nats.container \
    /etc/containers/systemd/wakir-nats.container
sudo install -m 644 wakir-orchestrator.network \
    /etc/containers/systemd/wakir-orchestrator.network
sudo install -m 644 wakir-nats-jetstream-data.volume \
    /etc/containers/systemd/wakir-nats-jetstream-data.volume

# Trigger the Quadlet generator (parses the .container/.network/
# .volume units into synthesised .service units in /run/systemd/).
sudo systemctl daemon-reload

# Bring the service up. The synthesised unit name follows the
# convention `wakir-nats.service` (matches the .container basename).
sudo systemctl start wakir-nats.service

# Verify health.
systemctl status wakir-nats.service
podman healthcheck run wakir-nats
nc -z 127.0.0.1 4222 && echo ok
curl -s http://127.0.0.1:8222/jsz | jq .

# Idempotent bucket initialisation (unchanged from the compose path).
python3 scripts/init-nats-buckets.py
```

### 2.3 Operator tear-down flow (Quadlet path)

```bash
# Stop and disable the service (the synthesised unit auto-disables
# on file removal, so this is belt-and-braces).
sudo systemctl stop wakir-nats.service

# Optional: drop the JetStream volume (cache loss is acceptable in
# Phase-1 per runbook §6.2).
podman volume rm wakir-nats-jetstream-data

# Optional: drop the bridge network.
podman network rm wakir-orchestrator
```

---

## 3 / Equivalence stamps (Quadlet ↔ compose)

| Compose field                                | Quadlet directive                          | Equivalent? |
|----------------------------------------------|--------------------------------------------|-------------|
| `image:`                                     | `Image=`                                   | yes (byte-precise digest pin preserved) |
| `container_name:`                            | `ContainerName=`                           | yes |
| `command:` (list form)                       | `Exec=` (shell form)                       | yes (semantic — Podman tokenises) |
| `ports:` `127.0.0.1:HOST:CTR`                | `PublishPort=127.0.0.1:HOST:CTR`           | yes |
| `volumes:` `name:/path`                      | `Volume=name.volume:/path`                 | yes (named volume) |
| `networks:` `[wakir]`                        | `Network=wakir-orchestrator.network`       | yes |
| `restart: unless-stopped`                    | `[Service] Restart=on-failure`             | near-equivalent (1) |
| `healthcheck.test: [CMD-SHELL, "..."]`       | `HealthCmd=...`                            | yes |
| `healthcheck.interval/timeout/retries/start_period` | `HealthInterval/Timeout/Retries/StartPeriod=` | yes |
| `cap_drop: [ALL]`                            | `DropCapability=ALL`                       | yes |
| `security_opt: [no-new-privileges:true]`     | `NoNewPrivileges=true`                     | yes |
| `deploy.resources.limits.cpus/memory`        | `PodmanArgs=--cpus= --memory=`             | yes (enforced under Quadlet — compose v2 deploy is advisory) |

**(1) restart-policy nuance:** compose `unless-stopped` is "restart
unless the operator explicitly stopped it." systemd `Restart=on-failure`
restarts only on non-zero exit. The closer systemd equivalent is
`Restart=always` with a `RestartPreventExitStatus=` allowlist, but
`Restart=on-failure` matches typical Phase-1b expectations (NATS
exits zero only on operator-driven `systemctl stop`). Operator may
opt into `Restart=always` if they want exit-code-blind restart.

---

## 4 / Boring-tech-bias check

### 4.1 Why Quadlet, not `podman generate systemd`

`podman generate systemd` (the pre-Quadlet path) is deprecated as
of Podman 4.6 (2023). It synthesises a `.service` unit by
serialising the container's runtime state into a long
`ExecStart=podman run ...` line. Disadvantages versus Quadlet:

- Brittle: any field change requires regenerating the .service file.
- Stateful: the generated file embeds the current container state
  (env vars, network IDs) rather than a declarative spec.
- Deprecated upstream.

Quadlet is the upstream-recommended pattern. Adopting `podman
generate systemd` today is taking on technical debt that upstream
already signposted.

### 4.2 Why not Kubernetes (k3s / kind / microshift)

Kubernetes is the Phase-3 cluster path. For a single-host atomic
operator, k3s/microshift adds:

- A control-plane (etcd, kube-apiserver, kube-controller-manager,
  kube-scheduler).
- A CNI plug-in.
- A kubelet supervising containerd or CRI-O.

For one NATS substrate container on one host, that is a 100x
complexity multiplier. Quadlet is one ini-style file parsed by a
systemd generator that already runs on the host.

### 4.3 Why not just leave it at `docker compose`

`docker compose` works on atomic hosts via `podman compose`. The
translation tax is real but small for one or two services. Leaving
it at compose-only is a defensible choice — this skizze does not
recommend deletion of `compose/nats.yaml`. Quadlet is an
**alternative path documented**, not a forced migration.

The trigger that would tip the balance toward Quadlet-as-primary:

- More than 3 long-running container services on the atomic host
  (boot-time orchestration starts to matter — systemd handles
  ordering and dependencies natively; compose-on-podman is less
  battle-tested for boot-time start).
- Operator-side preference for systemd journal as the unified log
  sink (Quadlet logs flow into `journalctl -u wakir-nats.service`
  by default; compose-on-podman logs flow into `podman logs`).
- Need for systemd-native socket activation (Phase-3 federation
  scenarios with cold-start optimisation).

None of these triggers are present in Phase-2. Recommendation:
**document the Quadlet path, keep compose as the primary surface,
revisit at Phase-3 cluster-design time**.

---

## 5 / Migration scenarios (when to switch)

### 5.1 Scenario A: stay on compose (recommended for Phase-2)

- `compose/nats.yaml` is the primary contract surface.
- Tests in `tests/orchestrator/test_compose_nats.py` continue to
  assert against the compose file.
- Operator-side host uses `podman compose -f compose/nats.yaml up -d`.
- Quadlet skizze (this document) is reference material for operators
  who want host-native systemd integration but is not committed as
  a runnable unit file.

### 5.2 Scenario B: dual-track (compose + Quadlet, both committed)

- Add `quadlet/wakir-nats.container`, `quadlet/wakir-orchestrator.network`,
  `quadlet/wakir-nats-jetstream-data.volume` to the repo.
- Add a parity test: `tests/orchestrator/test_quadlet_nats.py`
  asserts that the Quadlet `Image=` line matches the compose
  `image:` line byte-precise (digest-pin parity).
- Runbook §1 documents both bring-up paths; operator chooses.
- Cost: two contract surfaces to maintain in lock-step.

### 5.3 Scenario C: Quadlet as primary (Phase-3 trigger)

- `compose/nats.yaml` is retained for development-environment
  bring-up on non-atomic hosts (Linux laptops with Docker, macOS
  Docker Desktop).
- `quadlet/wakir-nats.container` is the production-host primary.
- Tests assert against the Quadlet unit, with a thin
  Quadlet→compose generator for the dev environment.
- Trigger: Phase-3 federation-substrate bring-up with 3+ services
  (NATS + SPIRE-server + OTel-collector + …) on the production
  atomic host.

**Phase-2 default: Scenario A. Phase-3 decision-point: Scenario B
or C, owner DevOps-side with Operator-Hand approval.**

---

## 6 / Open items (Tag-4 box-end + Sprint-6 Tag-1 update)

- **OI-Q1 (still open):** validate the Quadlet shape against a live
  atomic host (Bluefin or Silverblue VM). This skizze is paper-form
  + Sprint-6 Tag-1 committed-runnable-file-form; the live-smoke test
  on a real atomic host is still operator-hand per ADR-0051
  Mira-Sandbox-vs-Host-Operations-Trennung (no host-podman-socket
  access from sandbox). Estimated effort: 30-min operator box.
- **OI-Q2 (resolved Sprint-6 Tag-1):** Quadlet directive names
  verified against Podman 5.8.2 (`podman --version` on the
  authoring host, 2026-05-11) and against the upstream
  `podman-systemd.unit(5)` man-page (docs.podman.io, fetched
  2026-05-11). The directive surface used in
  `quadlet/wakir-nats.container` (`Image`, `Exec`, `PublishPort`,
  `Volume`, `Network`, `DropCapability`, `NoNewPrivileges`,
  `HealthCmd`, `HealthInterval`, `HealthTimeout`, `HealthRetries`,
  `HealthStartPeriod`, `PodmanArgs`) is current in Podman 5.x —
  no renames detected from the 4.4-doc-form. No directive deprecation
  flagged in the upstream 5.x docs as of fetch time.
- **OI-Q3 (partially resolved Sprint-6 Tag-1):** the **runnable
  Scenario-B dual-track skeleton** is now committed
  (`quadlet/wakir-nats.container` + sidecar `.network`/`.volume`
  units + `tests/orchestrator/test_quadlet_nats.py` parity tests
  16/16 green). This is **not** an adoption-decision shift —
  compose remains the primary Phase-2 contract surface, and the
  runbook §1 bring-up section still uses `docker compose -f
  compose/nats.yaml up -d` as the primary path. Quadlet is
  **available** for atomic-host operators who prefer host-native
  systemd integration, enforced byte-precise-aligned with compose
  via the parity tests. Scenario-C (Quadlet-as-primary) remains a
  Phase-3-trigger decision and stays operator-hand / CEO-side.
- **OI-Q4 (deferred to Phase-3):** if Quadlet becomes primary at
  Phase-3, the `tests/orchestrator/test_compose_nats.py` contract
  assertions need a Quadlet-equivalent refactor. The Sprint-6 Tag-1
  parity-test surface (`test_quadlet_nats.py`) is a partial-credit
  starting point — it currently asserts Quadlet-against-compose
  drift, not compose-against-Quadlet drift. A Phase-3 flip would
  reverse the dependency direction.

---

## 7 / Verifikations-Stempel (P5 + P7)

- **`date -u`:** 2026-05-11T19:51:59Z (P5).
- **`date -Iseconds`:** 2026-05-11T21:51:59+02:00 (P5 local).
- **Worktree:** `agents-workspaces/kai/wakir-runtime` (ADR-0049-
  konform, eigener Klon).
- **Branch:** `kai/phase-2-sprint-5-tag-4-quadlet-systemd-skizze`,
  forked from Sprint-5 Tag-3 tip `83d3b0e`.
- **Source-of-truth for compose-shape:** `compose/nats.yaml` at
  Sprint-5 Tag-3 tip `83d3b0e` (digest-pin
  `sha256:e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00`
  preserved byte-precise in §2.1 Quadlet skizze).
- **Tool-Verifikation (P7) — Tag-4 baseline + Sprint-6 Tag-1 update:**
  - Quadlet directives `Image=`, `Exec=`, `PublishPort=`, `Volume=`,
    `Network=`, `DropCapability=`, `NoNewPrivileges=`, `HealthCmd=`,
    `HealthInterval=`, `HealthTimeout=`, `HealthRetries=`,
    `HealthStartPeriod=`, `PodmanArgs=` are documented in the
    Podman 4.4+ Quadlet man-page (`podman-systemd.unit(5)`).
    **Sprint-6 Tag-1 verification:** the directive surface is also
    current in Podman 5.8.2 (verified via `podman --version` on
    authoring host plus docs.podman.io live-fetch 2026-05-11).
    No directive renames detected from 4.x baseline. **OI-Q2
    resolved.**
  - `podman generate systemd` deprecation status: deprecated as of
    Podman 4.6 release notes (2023). P2-stamp at Tag-4: cited from
    memory; Sprint-6 Tag-1 not re-verified live (no behavior change
    in this box — the dual-track does not use `podman generate
    systemd` anywhere).
- **Vermutungs-Kennzeichnung (P2):**
  - "Fedora 41+ Quadlet is the recommended lifecycle path" — based
    on Podman upstream documentation direction; not verified against
    a current Fedora-41 release-notes citation in this box.
  - "Bluefin / Silverblue / Kinoite all ship systemd + Podman" — true
    of Fedora-Atomic family generally; the specific Bluefin (uBlue
    fork) shipping state is conjecture-pending if the operator-side
    host uses a non-stock uBlue variant.
  - Quadlet `HealthCmd=` semantics: documented and directive-name-
    verified against Podman 5.8.2 in Sprint-6 Tag-1; runtime
    behavior (probe execution + Podman healthcheck integration) is
    still not live-tested in sandbox — remains OI-Q1 for operator-
    hand live-host verification.

- **Sprint-6 Tag-1 stamp:**
  - **`date -Iseconds`:** 2026-05-11T22:38:02+02:00 (box-start).
  - **Worktree:** `/tmp/kai-sprint-6-quadlet-dual-track` (own clone
    via `git worktree add` from `agents-workspaces/kai/wakir-runtime`,
    ADR-0049-konform).
  - **Branch:** `kai/phase-2-sprint-6-tag-1-quadlet-dual-track`,
    forked from Sprint-5 Tag-5 tip `fd0cc9e`.
  - **Sandbox-Trennung:** no host-podman-socket access from sandbox
    (Mira-Direktive 2026-05-11 / ADR-0051 rejected). Directive
    verification is doc-form against `podman --version 5.8.2`
    output and docs.podman.io — no `podman run` invocations from
    sandbox.

---

## 8 / Schluss

This skizze documents the Quadlet/systemd alternative lifecycle
shape for the Phase-1b NATS-JetStream substrate, alongside the
existing `compose/nats.yaml` primary contract surface.

**Tag-4 deliverable (2026-05-11 21:51 CEST):** design-form skizze,
no runnable `.container` file committed. Recommendation Scenario A
(stay on compose) for Phase-2 default.

**Sprint-6 Tag-1 update (2026-05-11 ~22:55 CEST):** **Scenario B
dual-track upgraded to committed-runnable-file form.** The
`quadlet/` directory now contains the runnable unit-file trio
(`wakir-nats.container`, `wakir-orchestrator.network`,
`wakir-nats-jetstream-data.volume`) plus a README and the
hermetic parity-test surface
`tests/orchestrator/test_quadlet_nats.py` (16/16 green). The
adoption recommendation is **unchanged**: compose remains the
primary Phase-2 contract surface; Quadlet is the host-native
alternative for atomic-distro operators who want systemd-native
lifecycle integration. Scenario C (Quadlet-as-primary) remains a
Phase-3-trigger decision and stays operator-hand / CEO-side.

No Z-A / Z-B / Z-C / Z-D cross-review touchpoints. No image-pin
change (byte-precise mirror of compose), no schema change, no
identity change, no Phala touch.

— Kai (Tag-4 author; Sprint-6 Tag-1 update author)
