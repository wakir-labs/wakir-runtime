# Quadlet dual-track for the Wakir Phase-1b/2 substrates

**Status:** Scenario-B dual-track (per
`docs/quadlet-systemd-migration-skizze.md` §5.2). Committed as a
runnable alternative to `compose/*.yaml` for atomic-distro
operator hosts. **Compose remains the primary Phase-2 contract
surface.** Tests in `tests/orchestrator/test_compose_*.py` are
authoritative; `tests/orchestrator/test_quadlet_*.py` asserts
that the Quadlet shape stays byte-precise-aligned with the compose
state (in particular the image digest pin and the hardening
posture).

Substrates with Quadlet dual-track coverage:

- **Phase-1b NATS-JetStream** (Sprint-6 Tag-1): mirror of
  `compose/nats.yaml`.
- **Phase-2.1 SPIRE-Server hermetic sidecar** (Sprint-6 Tag-11):
  mirror of `compose/spire.yaml` services.spire-server.
- **Phase-2.2 SPIRE-Agent hermetic sidecar** (Sprint-6 Tag-11):
  mirror of `compose/spire.yaml` services.spire-agent.

**Scope-disclaimer:** this dual-track is operator-facing
infrastructure surface. It does **not**:

- Change the Phase-1b container-identity story (Z-A non-touch).
- Change the NATS JetStream schema or bucket inventory (Z-B non-touch).
- Change the image-pin pipeline or digest verification (Z-C non-touch).
- Change the TEE / Phala-Cloud Phase-3 substrate (Z-D non-touch).

It is a pure lifecycle-manager-shape addition with byte-precise
content alignment to the existing compose state.

---

## Files

| File | Type | Purpose |
|---|---|---|
| `wakir-nats.container` | Quadlet container unit | Phase-1b NATS-JetStream substrate, mirror of `compose/nats.yaml` services.nats |
| `wakir-orchestrator.network` | Quadlet network unit | Bridge network, mirror of `compose/nats.yaml` networks.wakir |
| `wakir-nats-jetstream-data.volume` | Quadlet volume unit | JetStream persistence, mirror of `compose/nats.yaml` volumes.jetstream_data |
| `wakir-spire-server.container` | Quadlet container unit | Phase-2.1 SPIRE-Server, mirror of `compose/spire.yaml` services.spire-server |
| `wakir-spire-server-data.volume` | Quadlet volume unit | SPIRE-Server datastore + bootstrap-CA, mirror of `compose/spire.yaml` volumes.spire_server_data |
| `wakir-spire-server-sockets.volume` | Quadlet volume unit | Admin-API gRPC socket-share (Server <-> Agent), mirror of `compose/spire.yaml` volumes.spire_server_sockets |
| `wakir-spire-agent.container` | Quadlet container unit | Phase-2.2 SPIRE-Agent, mirror of `compose/spire.yaml` services.spire-agent |
| `wakir-spire-agent-data.volume` | Quadlet volume unit | SPIRE-Agent SVID cache + bootstrap-bundle, mirror of `compose/spire.yaml` volumes.spire_agent_data |
| `wakir-spire-agent-sockets.volume` | Quadlet volume unit | SPIFFE-Workload-API socket-share (Agent <-> persona-container), mirror of `compose/spire.yaml` volumes.spire_agent_sockets |
| `wakir-rust-cli.container` | Quadlet container unit | Tag-22/24 Phase-3b Rust-CLI host-side binary installer oneshot (seven binaries from carrier image `wakir-persona-engine` -> `/opt/wakir/bin/`) |
| `wakir-rust-cli-bin.volume` | Quadlet volume unit | Tag-22 Phase-3b Rust-CLI host-side binary volume mounted by `wakir-rust-cli.container` |

For the Tag-22 Phase-3b Rust-CLI installer Operator recipe see
[`docs/operations/quadlets-phase-3b-rust-cli.md`](../docs/operations/quadlets-phase-3b-rust-cli.md).

---

## Operator bring-up (atomic-host-native path)

### Rootful Podman (production atomic host)

```bash
# Install unit files into the systemd-generators search path.
sudo install -m 644 quadlet/wakir-nats.container \
    /etc/containers/systemd/wakir-nats.container
sudo install -m 644 quadlet/wakir-orchestrator.network \
    /etc/containers/systemd/wakir-orchestrator.network
sudo install -m 644 quadlet/wakir-nats-jetstream-data.volume \
    /etc/containers/systemd/wakir-nats-jetstream-data.volume

# Trigger the Quadlet generator.
sudo systemctl daemon-reload

# Bring the service up.
sudo systemctl start wakir-nats.service

# Verify (host-operator-hand, NOT in sandbox).
systemctl status wakir-nats.service
podman healthcheck run wakir-nats
nc -z 127.0.0.1 4222 && echo ok
curl -s http://127.0.0.1:8222/jsz | jq .

# Idempotent bucket init (unchanged from compose path).
python3 scripts/init-nats-buckets.py
```

### Rootless Podman (development workstation)

```bash
mkdir -p ~/.config/containers/systemd
cp quadlet/wakir-nats.container \
    quadlet/wakir-orchestrator.network \
    quadlet/wakir-nats-jetstream-data.volume \
    ~/.config/containers/systemd/

systemctl --user daemon-reload
systemctl --user start wakir-nats.service
```

---

## SPIRE bring-up (Phase-2.1/2.2 atomic-host-native path)

The SPIRE substrate adds two container units (server + agent) and
four named-volume sidecars on top of the NATS substrate. The agent
depends on the server's healthcheck (see "systemd ordering" in
`wakir-spire-agent.container`).

### Rootful Podman (production atomic host)

```bash
# Pre-condition: NATS substrate already running (network is shared).

# Install SPIRE-Server unit + named volumes.
sudo install -m 644 quadlet/wakir-spire-server.container \
    /etc/containers/systemd/wakir-spire-server.container
sudo install -m 644 quadlet/wakir-spire-server-data.volume \
    /etc/containers/systemd/wakir-spire-server-data.volume
sudo install -m 644 quadlet/wakir-spire-server-sockets.volume \
    /etc/containers/systemd/wakir-spire-server-sockets.volume

# Install SPIRE-Agent unit + named volumes.
sudo install -m 644 quadlet/wakir-spire-agent.container \
    /etc/containers/systemd/wakir-spire-agent.container
sudo install -m 644 quadlet/wakir-spire-agent-data.volume \
    /etc/containers/systemd/wakir-spire-agent-data.volume
sudo install -m 644 quadlet/wakir-spire-agent-sockets.volume \
    /etc/containers/systemd/wakir-spire-agent-sockets.volume

# Install the bind-mounted Mock/Stub configs (host-side).
sudo install -m 644 config/spire-server.conf \
    /etc/wakir/spire-server.conf
sudo install -m 644 config/spire-agent.conf \
    /etc/wakir/spire-agent.conf

# Trigger the Quadlet generator and bring up.
sudo systemctl daemon-reload
sudo systemctl start wakir-spire-server.service
sudo systemctl start wakir-spire-agent.service

# Verify (host-operator-hand, NOT in sandbox).
systemctl status wakir-spire-server.service
systemctl status wakir-spire-agent.service
podman healthcheck run wakir-spire-server
podman healthcheck run wakir-spire-agent
```

### Image-digest-pin Operator-Hand workflow

Both SPIRE unit files carry a Cosign-Digest-Pin placeholder token
`DIGEST_PENDING_TOMAS_REVIEW`. Before any live bring-up, Operator-
Hand resolves the canonical 64-hex digest via `cosign verify` +
`skopeo inspect` and substitutes both surfaces (compose + Quadlet)
in the same commit. The parity test
`tests/orchestrator/test_quadlet_spire.py` accepts both forms so
the substitution does not break the contract surface. Cross-Review
Zone-C (Tomás-track) approves the digest before substitution.

---

## Compose vs Quadlet — operator decision matrix

| Host environment | Recommended path |
|---|---|
| macOS Docker Desktop / Linux laptop with Docker | `compose/nats.yaml` via `docker compose -f compose/nats.yaml up -d` |
| Linux laptop with Podman | either path — `podman compose -f compose/nats.yaml up -d` or Quadlet rootless |
| Fedora Atomic / Bluefin / Silverblue / Kinoite (production) | **Quadlet** (host-native, journalctl-integrated, boot-ordered) |

Decision rationale lives in
`docs/quadlet-systemd-migration-skizze.md` §4 (Boring-tech-bias
check) and §5 (Migration scenarios).

---

## Parity contract with compose

Both surfaces describe the same Phase-1b NATS-JetStream substrate.
The parity contract is enforced by
`tests/orchestrator/test_quadlet_nats.py`:

| Contract field | Compose | Quadlet | Parity test |
|---|---|---|---|
| Image digest pin | `services.nats.image` | `[Container] Image=` | byte-precise digest match |
| Container name | `services.nats.container_name` | `[Container] ContainerName=` | string match |
| Port publication | `services.nats.ports` | `[Container] PublishPort=` | loopback-only invariant |
| JetStream enable | `services.nats.command` `--jetstream` | `[Container] Exec=` `--jetstream` | substring presence |
| Store directory | `services.nats.command` `--store_dir=/data/jetstream` | `[Container] Exec=` `--store_dir=/data/jetstream` | substring presence |
| Volume mount | `services.nats.volumes` | `[Container] Volume=` | volume name + mountpoint match |
| Network attach | `services.nats.networks` | `[Container] Network=` | network name match |
| Capabilities | `services.nats.cap_drop` `[ALL]` | `[Container] DropCapability=ALL` | enum match |
| Privileges | `services.nats.security_opt` `no-new-privileges:true` | `[Container] NoNewPrivileges=true` | flag match |
| Health probe endpoint | `services.nats.healthcheck.test` `/jsz` | `[Container] HealthCmd=` `/jsz` | substring presence |

When any compose field changes, the corresponding Quadlet field
**must** be updated in the same commit. The parity test surface
catches drift hermetically (no container engine needed for the
test run).

### SPIRE-Server parity contract

| Contract field | Compose (services.spire-server) | Quadlet (wakir-spire-server.container) | Parity test |
|---|---|---|---|
| Image (Cosign-Digest-Pin) | `image: ghcr.io/.../spire-server:1.14.6@sha256:...` | `[Container] Image=` | byte-precise digest or placeholder |
| Container name | `container_name: wakir-spire-server` | `[Container] ContainerName=` | string match |
| Port publication | `ports: ["127.0.0.1:8081:8081"]` | `[Container] PublishPort=` | loopback-only invariant |
| Exec / command | `command: [run, -config, ...]` | `[Container] Exec=` | substring presence |
| Config bind-mount | `volumes: ["./config/spire-server.conf:...:ro"]` | `[Container] Volume=...:ro,Z` | path + ro flag |
| Data volume | `volumes: [spire_server_data:/var/lib/spire/server]` | `[Container] Volume=wakir-spire-server-data.volume:...` | named-volume + mountpoint |
| Server-sockets volume | `volumes: [spire_server_sockets:/run/spire/sockets]` | `[Container] Volume=wakir-spire-server-sockets.volume:...` | shared with agent |
| Network attach | `networks: [wakir]` | `[Container] Network=wakir-orchestrator.network` | shared with NATS substrate |
| Read-only rootfs | `read_only: true` | `[Container] ReadOnly=true` | flag match |
| User | `user: "1000:1000"` | `[Container] User=1000` + `Group=1000` | uid + gid match |
| Tmpfs | `tmpfs: ["/run/spire:rw,size=16m,mode=0700"]` | `[Container] Tmpfs=/run/spire:...` | path presence |
| Capabilities | `cap_drop: [ALL]` | `[Container] DropCapability=ALL` | enum match |
| Privileges | `security_opt: [no-new-privileges:true]` | `[Container] NoNewPrivileges=true` | flag match |
| Health probe binary | `healthcheck.test: [CMD, /opt/spire/bin/spire-server, healthcheck]` | `[Container] HealthCmd=/opt/spire/bin/spire-server healthcheck` | binary + subcommand |

### SPIRE-Agent parity contract

| Contract field | Compose (services.spire-agent) | Quadlet (wakir-spire-agent.container) | Parity test |
|---|---|---|---|
| Image (version-parity with server) | `image: ghcr.io/.../spire-agent:1.14.6@sha256:...` | `[Container] Image=` | digest or placeholder + SemVer match |
| Container name | `container_name: wakir-spire-agent` | `[Container] ContainerName=` | string match |
| No host ports | (no `ports:` field) | (no `PublishPort=` directive) | absence-of-port invariant |
| Boot ordering | `depends_on: spire-server: condition: service_healthy` | `[Unit] After=/Requires=wakir-spire-server.service` | systemd-equivalent |
| Config bind-mount | `volumes: ["./config/spire-agent.conf:...:ro"]` | `[Container] Volume=...:ro,Z` | path + ro flag |
| Agent-data volume | `volumes: [spire_agent_data:/var/lib/spire/agent]` | `[Container] Volume=wakir-spire-agent-data.volume:...` | named-volume + mountpoint |
| Server-sockets share | `volumes: [spire_server_sockets:/run/spire/sockets]` | `[Container] Volume=wakir-spire-server-sockets.volume:...` | mounted at same path as server |
| Agent-sockets (Workload-API) | `volumes: [spire_agent_sockets:/run/spire/agent-sockets]` | `[Container] Volume=wakir-spire-agent-sockets.volume:...` | named-volume + mountpoint |
| All other hardening directives | (parity with server) | (parity with server) | parametrised tests cover both |

The `tests/orchestrator/test_quadlet_spire.py` suite enforces these
contracts hermetically — no container engine, no systemd, no live
SPIRE-Server, no SVID issuance.

---

## Open items (Sprint-6 box-end)

- **OI-Q1 (carryover from Tag-4 Skizze):** Live-host smoke against a
  real atomic-distro VM (Bluefin or Silverblue). Sandbox-trennung
  per ADR-0051 means this is operator-hand, not DevOps-solo. P2
  marker: the Quadlet directive shape is doc-form-verified against
  Podman 5.8.2 manual but not yet live-tested on a Wakir-baseline
  atomic-host install.
- **OI-Q3 (resolved this box, partial):** Tag-4 Skizze flagged
  Scenario-B commitment as "operator-Hand / CEO-side strategy call,
  not DevOps-solo." This dual-track commits the **runnable-file
  skeleton** but does not change the recommendation: compose
  remains the primary Phase-2 contract surface. Adopting Quadlet
  as primary (Scenario C) is still a Phase-3-trigger decision and
  remains operator-hand.
- **OI-Q4 (deferred to Phase-3):** If Quadlet becomes primary at
  Phase-3, the compose-test surface needs a Quadlet-equivalent
  refactor. Estimated effort: one Phase-3-Sprint-N box.

---

## Verification (P5 + P7 stamps)

- Quadlet directive surface: verified against Podman 5.8.2
  (`podman --version` on this host) and against the upstream
  `podman-systemd.unit(5)` man-page (fetched 2026-05-11 via
  docs.podman.io). All directives used in `wakir-nats.container`
  are documented in the [Container] section: `Image`, `Exec`,
  `PublishPort`, `Volume`, `Network`, `DropCapability`,
  `NoNewPrivileges`, `HealthCmd`, `HealthInterval`,
  `HealthTimeout`, `HealthRetries`, `HealthStartPeriod`,
  `PodmanArgs`. **OI-Q2 resolved.**
- Image-digest-pin alignment: byte-precise mirror of
  `compose/nats.yaml` Sprint-4 Tag-3 digest-pin
  `sha256:e4bf19f15fd3218814a4e3c9e0064e1334bd8aa20d5984b9f1a0afd084f8cc00`.
  Parity test enforces this hermetically.
- Hermetic-only: no container engine invocations during test runs.
  Live-smoke remains operator-hand per CEO-side sandbox/host-
  operations separation directive 2026-05-11 (ADR-0051 rejected,
  host-podman-socket explicitly off-limits to sandbox).
