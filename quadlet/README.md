# Quadlet dual-track for the Phase-1b NATS substrate

**Status:** Scenario-B dual-track (per
`docs/quadlet-systemd-migration-skizze.md` §5.2). Committed as a
runnable alternative to `compose/nats.yaml` for atomic-distro
operator hosts. **Compose remains the primary Phase-2 contract
surface.** Tests in `tests/orchestrator/test_compose_nats.py` are
authoritative; `tests/orchestrator/test_quadlet_nats.py` asserts
that the Quadlet shape stays byte-precise-aligned with the compose
state (in particular the image digest pin).

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
