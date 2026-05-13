# SPIRE-Agent-Sidecar Federation-Wiring (Phase-2 Sprint-8 Tag-2)

**Status:** Hermetic substrate. Live bring-up is Operator-Hand per
[`feedback_sandbox_host_trennung.md`][sandbox-trennung]. The sandbox
does NOT touch the host's podman socket.

[sandbox-trennung]: ../../../.claude/feedback_sandbox_host_trennung.md

This directory carries the Phase-2 Sprint-8 Tag-2 SPIRE-Agent-Sidecar
substrate wired into the Sprint-8 Tag-1 Federation-Bundle-Endpoint.
Two SPIRE-Agent containers (one per Tag-1 trust-domain: `wakir.test` +
`partner.test`) attest against their side's SPIRE-Server, ingest the
federated peer-bundles via the Tag-1 bundle-endpoint listener, and
serve the SPIFFE-Workload-API on per-side named volumes that
Phase-2.3+ persona-containers will mount read-only.

## Layer-Wiring

Tag-2 closes the loop between the SPIFFE substrate sprints:

| Sprint / Tag | Substrate | Status |
|---|---|---|
| Sprint-6 Tag-9 | SPIRE-Agent (single trust-domain `example.test`) | Phase-2.2, in `compose/spire.yaml` |
| Sprint-8 Tag-1 | SPIRE-Federation-Bundle-Endpoint (two SPIRE-Servers) | Phase-2c, in `infra/spire/federation/` |
| **Sprint-8 Tag-2 (this directory)** | **SPIRE-Agent wired into Tag-1 federation servers** | **Phase-2c, in `infra/spire/agent/`** |

After Tag-2, an Operator can mint a workload-X.509-SVID in `wakir.test`
on the wakir-side agent, present it to a workload connected through
the partner-side agent, and the partner-side verifies it against the
Tag-1-federated `wakir.test` trust-bundle. That cross-trust-domain
roundtrip is the Operator-Hand-pendet acceptance evidence (§3b below).

## Files

| Path | Role |
|---|---|
| `compose/spire-agent-federation.yaml` | Two-agent compose substrate (external network + bundles volumes from Tag-1). |
| `config/spire-agent-wakir.conf` | `wakir.test` side SPIRE-Agent config. |
| `config/spire-agent-partner.conf` | `partner.test` side SPIRE-Agent config. |
| `bin/spire-agent-fed-attest` | Mock CLI for cross-trust-domain SVID issuance + JWT-SVID-fallback. |
| `bin/spire_agent_fed_attest.py` | CLI module (import target for tests). |
| `quadlet/wakir-spire-agent-federation.container` | Per-side Quadlet template (placeholders `<SIDE>`, `<TRUST_DOMAIN>`, `<SERVER_DNS>`). |
| `quadlet/wakir-spire-agent-federation-data.volume` | Per-side data volume template. |
| `quadlet/wakir-spire-agent-federation-sockets.volume` | Per-side Workload-API sockets volume template. |
| `tests/test_compose_spire_agent_federation.py` | Compose-shape invariants. |
| `tests/test_spire_agent_federation_config.py` | Agent-config-shape invariants. |
| `tests/test_spire_agent_fed_attest_cli.py` | CLI Mock determinism + JWT-fallback contract. |
| `tests/test_quadlet_spire_agent_federation.py` | Quadlet template parity. |

## 1. Compose substrate

Two SPIRE-Agent containers on the **external** `wakir-federation`
bridge network (Tag-1-owned). Each agent reads the **external**
side-specific `wakir-spire-server-<SIDE>-bundles` volume read-only for
the bootstrap trust-bundle ingest, and writes its Workload-API socket
to a per-side **internal** `wakir-spire-agent-<SIDE>-sockets` volume.

| Side | Container | Server target | Workload-API socket volume |
|---|---|---|---|
| `wakir.test` | `wakir-spire-agent-wakir` | `spire-server-wakir:8081` | `wakir-spire-agent-wakir-sockets` |
| `partner.test` | `wakir-spire-agent-partner` | `spire-server-partner:8081` | `wakir-spire-agent-partner-sockets` |

The agents communicate with their side's SPIRE-Server over the bridge
network's internal DNS (`spire-server-wakir` / `spire-server-partner`).
No host port-publish on the agent side — the Workload-API is unix-
socket-only.

## 2. Bring-up (Operator-Hand, NOT auto from sandbox)

```bash
# Pre-condition: Tag-1 federation substrate must already be up.
cd infra/spire/federation
podman compose -f compose/spire-federation.yaml up -d

# Bootstrap-trust-bundle: stage the per-side server's own bundle into
# the bundles volume (the agent's trust_bundle_path reads
# /var/lib/spire/bundles/bootstrap.jwks read-only).
podman exec wakir-spire-server-wakir \
    /opt/spire/bin/spire-server bundle list -format jwks \
    > /tmp/wakir.jwks
podman cp /tmp/wakir.jwks \
    wakir-spire-server-wakir:/var/lib/spire/bundles/bootstrap.jwks

podman exec wakir-spire-server-partner \
    /opt/spire/bin/spire-server bundle list -format jwks \
    > /tmp/partner.jwks
podman cp /tmp/partner.jwks \
    wakir-spire-server-partner:/var/lib/spire/bundles/bootstrap.jwks

# Now bring up the Tag-2 agents alongside.
cd ../agent
podman compose -f compose/spire-agent-federation.yaml up -d
podman compose -f compose/spire-agent-federation.yaml ps
```

Both agents should reach `healthy` status within ~30 s. The
`healthcheck` invokes `spire-agent healthcheck` inside each container.

Tear-down:

```bash
podman compose -f compose/spire-agent-federation.yaml down -v
cd ../federation
podman compose -f compose/spire-federation.yaml down -v
```

The `-v` drops the internal named volumes (agent data + sockets); the
**external** federation network + bundles volumes are NOT touched by
the agent compose unit (lifecycle-isolated, Tag-1-owned).

## 3. Cross-trust-domain X.509-SVID issuance

### 3a. Hermetic CLI roundtrip (sandbox-safe)

The `spire-agent-fed-attest` Mock CLI exercises the selector-to-trust-
domain mapping pattern hermetically:

```bash
# From the repo root:
pytest infra/spire/agent/tests/test_spire_agent_fed_attest_cli.py -v
```

Manual roundtrip:

```bash
# Mint a wakir.test workload-SVID for selector uid=1000, gid=1000,
# path=/usr/bin/wirelang.
./bin/spire-agent-fed-attest fetch-x509 \
    --selector "1000:1000:/usr/bin/wirelang" \
    --trust-domain wakir.test

# Mint the same selector under partner.test — different SPIFFE-ID,
# different cert_hint (selector-to-trust-domain mapping is the Tag-2
# substrate invariant).
./bin/spire-agent-fed-attest fetch-x509 \
    --selector "1000:1000:/usr/bin/wirelang" \
    --trust-domain partner.test
```

The Mock CLI is **deterministic** — same inputs always yield the same
output. No clock, no random, no network.

### 3b. Live cross-trust-domain X.509-SVID verify (Operator-Hand)

With both Tag-1 federation servers and Tag-2 federation agents up, the
live X.509-SVID cross-trust verify is the Sprint-8 Tag-2 acceptance
evidence. The Operator performs this on the host (sandbox does NOT
have podman socket access):

```bash
# Register a workload entry on the wakir-side server.
podman exec wakir-spire-server-wakir \
    /opt/spire/bin/spire-server entry create \
    -parentID spiffe://wakir.test/spire/agent/join_token/<join-token> \
    -spiffeID spiffe://wakir.test/workload/echo \
    -selector unix:uid:1000 \
    -federatesWith partner.test

# Fetch the X.509-SVID via the wakir-side agent's Workload-API socket.
sudo podman exec wakir-spire-agent-wakir \
    /opt/spire/bin/spire-agent api fetch x509 \
    -socketPath /run/spire/agent-sockets/api.sock

# Expected output (P2 vermutung — verified P7 on first live run):
#   SPIFFE ID         : spiffe://wakir.test/workload/echo
#   SVID Valid After  : <timestamp>
#   SVID Valid Until  : <timestamp>
#   Bundle (1 entries):
#     spiffe://wakir.test     <CA-fingerprint>
#   Federated Bundles (1 entries):
#     spiffe://partner.test   <peer-CA-fingerprint>
```

The `Federated Bundles` block in the output is the Sprint-8 Tag-2
acceptance proof: the agent has consumed the federated peer-bundle and
can present cross-trust-verifiable X.509-SVIDs to partner-side workloads.

## 4. JWT-SVID Fallback Path (Reza-RealAdapter Anbindung)

Reza's `RealNatsConnectionAdapter` (Sprint-8 Tag-1
`wirelang/adapters/real_nats_adapter/`) consumes a SPIRE-Workload-API
JWT-SVID for NATS-JWT-Auth. When the operator disables SPIFFE substrate
(or in dev-mode without SPIRE) the adapter falls back to
`auth_mode="mock-jwt"`:

| `SPIRE_AGENT_SOCKET` env | RealAdapter `auth_mode` | Source of JWT |
|---|---|---|
| unset / empty / `"none"` | `"mock-jwt"` | Hermetic Mock (Reza-side) |
| valid unix-socket path | `"live-spiffe"` | SPIRE-Agent Workload-API |

Tag-2 produces the **SPIRE-Agent side** of the `"live-spiffe"` path
(`/run/spire/agent-sockets/api.sock` from the
`wakir-spire-agent-<SIDE>-sockets` volume). The `mock-jwt` path is
exercised in test by both ends — the `spire-agent-fed-attest fetch-jwt`
Mock CLI emits an `auth_mode_marker="mock-jwt"` literal that matches
Reza's RealAdapter constant, so the end-to-end fallback contract is
testable hermetically from both ends without live SPIRE:

```bash
# Mock JWT-SVID with audience-binding (matches RealAdapter shape).
./bin/spire-agent-fed-attest fetch-jwt \
    --selector "1000:1000:/usr/bin/wirelang" \
    --audience "nats://wakir-orchestrator" \
    --trust-domain wakir.test
# Returns JSON with auth_mode_marker="mock-jwt".
```

The fallback contract is asserted in
`tests/test_spire_agent_fed_attest_cli.py::test_fetch_jwt_emits_mock_jwt_auth_mode_marker`.

## 5. Operator-Hand Live-Verify Recipe

This is the same recipe pattern as Tag-1 README §3b. The sandbox does
NOT execute these commands; the Operator runs them on the Fedora host:

```bash
# Verify each agent's healthcheck status.
podman healthcheck run wakir-spire-agent-wakir
podman healthcheck run wakir-spire-agent-partner

# Fetch X.509-SVID from each agent's Workload-API socket.
sudo podman exec wakir-spire-agent-wakir \
    /opt/spire/bin/spire-agent api fetch x509 \
    -socketPath /run/spire/agent-sockets/api.sock

sudo podman exec wakir-spire-agent-partner \
    /opt/spire/bin/spire-agent api fetch x509 \
    -socketPath /run/spire/agent-sockets/api.sock

# Verify Workload-API socket permissions (peer-credential socket).
podman exec wakir-spire-agent-wakir \
    stat -c '%a %u %g' /run/spire/agent-sockets/api.sock
# Expected: 0660 1000 1000 (read/write for owner+group, no other)
# Persona-containers must run as uid:gid=1000:1000 OR be in the
# spire-sockets group for the Workload-API to accept their peer-cred.
```

The Operator posts the per-side `api fetch x509` output (or the
`Federated Bundles` line from §3b) as the Sprint-8 Tag-2 acceptance
evidence.

## 6. Cross-Review Gates

| Zone | Counterparty | Item | Status |
|---|---|---|---|
| Zone A | Reza (Wirelang) | SPIFFE-trust-domain literals (`wakir.test`/`partner.test`) match Tag-1 federation pair. Workload-API socket-path follows SPIFFE-spec canonical `/run/spire/agent-sockets/api.sock`. | Tag-2 inherits Tag-1 Zone-A ack (no new literal). |
| Zone B | Reza (NATS-Schema) | None — agent substrate does NOT use NATS. | Tag-2 unaffected. |
| Zone C | Tomás (Container-Image-Pipeline × OTS-Anchoring) | Cosign-Digest-Pin placeholder `DIGEST_PENDING_TOMAS_REVIEW` resolves to canonical sha256 digest before live bring-up — same workflow as Tag-1 federation server (Sprint-8 Tag-1 README §5 inherits). | Tag-2 inherits Tag-1 Zone-C ack (image-pin form parity). |
| Zone D | Reza (V-904 Identity-Bridge) | Federation-agent substrate is V-908 Phase-2-3 surface, not V-904 (Phala-Cloud). | Not applicable. |

## 7. Hermetic test surface

```bash
# From the repo root:
pytest infra/spire/agent/tests/ -v
```

Four test files, **63 tests, all green**:

* `test_compose_spire_agent_federation.py` — 16 compose-shape
  invariants (image-pin form, hardening posture, per-side volume
  wiring, external network + bundles volume, Workload-API socket-path).
* `test_spire_agent_federation_config.py` — 18 agent-config-shape
  invariants (trust-domain literals, server-address per side,
  trust_bundle_path/format wiring, insecure_bootstrap=false, plugin
  shape, cross-side trust-domain isolation in HCL body).
* `test_spire_agent_fed_attest_cli.py` — 18 CLI Mock invariants
  (X.509-SVID Mock, JWT-SVID Mock with `mock-jwt` auth_mode_marker
  fallback contract, determinism, audience-binding, selector
  validation, exit-code convention).
* `test_quadlet_spire_agent_federation.py` — 11 Quadlet template
  parity invariants (placeholders, image-pin, hardening directives,
  unit ordering, per-side volume references, no bundles-volume re-
  declaration).

The Sprint-8 Tag-2 acceptance is **green hermetic test surface + this
README shipped; live cross-trust SVID verify is Operator-Hand-pendet
per ADR-0051**.

## 8. Known follow-ups (Phase-2c / Sprint-9+)

* **Phase-2.3 persona-Workload-API consumer wiring** — the
  `wakir-spire-agent-<SIDE>-sockets` volume is ready; the Phase-2.3
  task wires a sample persona-sidecar to mount it read-only and
  fetch its SVID. Reza-Sprint-7 Tag-3
  `SpiffeCrossTrustDomainBridge` consumes the live-impl side once
  that lands.
* **NATS-JWT-Auth integration** — the RealAdapter live path
  (`SPIRE_AGENT_SOCKET=<unix-socket>` → `auth_mode="live-spiffe"`)
  needs the NATS-server-side JWT-callback impl. Phase-2.4 surface
  (separate from this Tag-2 substrate).
* **Trust-Bundle-Rotation drill on the federation-agent surface** —
  Sprint-6 Tag-12 rotation runbook covers the single-server case;
  the federation-agent case needs the agent's federated-bundle
  refresh cadence verified (refresh_hint cycle). Phase-3a tune slot.
* **Live cross-trust X.509-SVID roundtrip evidence** — Operator-Hand,
  posted after first bring-up. The README §3b recipe is the canonical
  workflow.
* **K8s-native equivalent** — Phase-3 Helm-chart for K8s consumers
  (ADR-0020 Box-5).

---
*— Kai*
