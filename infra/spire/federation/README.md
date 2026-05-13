# SPIRE-Federation-Bundle-Endpoint (Phase-2 Sprint-8 Tag-1)

**Status:** Hermetic substrate. Live bring-up is Operator-Hand per
[`feedback_sandbox_host_trennung.md`][sandbox-trennung]. The sandbox does
NOT touch the host's podman socket.

[sandbox-trennung]: ../../../../.claude/feedback_sandbox_host_trennung.md

This directory carries the Phase-2 Sprint-8 Tag-1 SPIRE-Federation-
Bundle-Endpoint substrate: two SPIRE-Server containers in two distinct
hermetic trust-domains (`wakir.test` and `partner.test`), wired so each
server's federation-bundle-endpoint listener is reachable to the other's
HTTPS-SPIFFE-profile peer-fetch. Substrate is the live counterpart to
Reza's Sprint-7 Tag-3 SPIFFE-Cross-Trust-Domain-Bridge
(`wirelang/federation/spiffe_cross_trust_domain_bridge.py`) — the bridge
consumes the federation-bundle-endpoint via pluggable
`PeerTrustBundleFetcher` and `PeerSvidVerifier` Protocols, and this
substrate is the live impl those Protocols target in Phase-2c+.

## Files

| Path | Role |
|---|---|
| `compose/spire-federation.yaml` | Two-server compose substrate (Mock/Stub). |
| `config/spire-server-wakir.conf` | `wakir.test` side SPIRE-Server config. |
| `config/spire-server-partner.conf` | `partner.test` side SPIRE-Server config. |
| `bin/spire-fed-bundle` | Bundle Export/Import CLI (hermetic-fixture JWKS). |
| `bin/spire_fed_bundle.py` | CLI module (import target for tests). |
| `quadlet/wakir-spire-server-federation.container` | Quadlet template (placeholders for `<SIDE>`, `<HOST_BUNDLE_PORT>`, `<HOST_GRPC_PORT>`). |
| `quadlet/wakir-federation.network` | Quadlet bridge-network sidecar. |
| `quadlet/wakir-spire-server-federation-{data,sockets,bundles}.volume` | Quadlet named-volume sidecars (per-side via placeholder). |
| `tests/test_federation_compose.py` | Hermetic compose-shape + config-shape invariants. |
| `tests/test_spire_fed_bundle_cli.py` | Hermetic CLI roundtrip + trust-domain mismatch guard. |
| `tests/test_federation_quadlet.py` | Compose ↔ Quadlet byte-precision parity. |

## 1. Compose substrate

Two SPIRE-Server containers on a dedicated `wakir-federation` bridge
network (isolated from the Sprint-6 `wakir-orchestrator` network). Each
server's bundle-endpoint listener binds container port `8443`. Host
loopback port-publish:

| Side | Bundle-endpoint (host) | gRPC API (host) | Container |
|---|---|---|---|
| `wakir.test` | `127.0.0.1:8443` | `127.0.0.1:8082` | `wakir-spire-server-wakir` |
| `partner.test` | `127.0.0.1:8444` | `127.0.0.1:8083` | `wakir-spire-server-partner` |

The two containers reach each other over the bridge network's internal
DNS (`spire-server-wakir`, `spire-server-partner`), NOT over the host's
loopback. Host port-publish is loopback-only and exists for operator
introspection during bring-up.

## 2. Bring-up (Operator-Hand, NOT auto from sandbox)

```bash
cd infra/spire/federation
podman compose -f compose/spire-federation.yaml up -d
podman compose -f compose/spire-federation.yaml ps
```

Both services should reach `healthy` status within ~30 s. The
`healthcheck` invokes `spire-server healthcheck` inside each container.

Tear-down:

```bash
podman compose -f compose/spire-federation.yaml down -v
```

The `-v` drops the named volumes (data, sockets, bundles) — bootstrap-CA
loss is acceptable in hermetic mode.

## 3. Bundle roundtrip + cross-trust X.509-SVID verify

The Sprint-8 Tag-1 acceptance is the cross-trust-domain bundle
roundtrip. Two variants:

### 3a. Hermetic CLI roundtrip (sandbox-safe)

Runs against the `spire-fed-bundle` CLI with hermetic-fixture JWKS —
no SPIRE-Server, no podman, no live. The
`tests/test_spire_fed_bundle_cli.py` suite exercises this end-to-end.

```bash
# From the repo root:
pytest infra/spire/federation/tests/test_spire_fed_bundle_cli.py -v
```

Manual roundtrip:

```bash
./bin/spire-fed-bundle export \
    --trust-domain wakir.test \
    --out /tmp/wakir.jwks

./bin/spire-fed-bundle import \
    --from-file /tmp/wakir.jwks \
    --as-trust-domain wakir.test \
    --out /tmp/wakir-at-partner.jwks

# Cross-import fails (trust-domain mismatch guard):
./bin/spire-fed-bundle import \
    --from-file /tmp/wakir.jwks \
    --as-trust-domain partner.test
# spire-fed-bundle: error: JWK #0 in /tmp/wakir.jwks carries hermetic-fixture
# marker _wakir_trust_domain='wakir.test' but import requested
# as-trust-domain='partner.test'; trust-domain mismatch
```

### 3b. Live cross-trust-domain bundle roundtrip (Operator-Hand)

With the compose substrate up, the live roundtrip uses the SPIRE-Server's
own `bundle list` / `bundle set` subcommands inside each container. From
the operator's host:

```bash
# Export the wakir.test trust-bundle from the wakir-side SPIRE-Server,
# JWKS-format, into the shared bundles volume.
podman exec wakir-spire-server-wakir \
    /opt/spire/bin/spire-server bundle list -format jwks \
    > /tmp/wakir.jwks

# Copy it into the partner-side bundles volume so the partner SPIRE-
# Server can set it as the wakir.test peer-trust-anchor.
podman cp /tmp/wakir.jwks wakir-spire-server-partner:/var/lib/spire/bundles/wakir.jwks

# Set the wakir.test bundle as a federated trust-bundle on the partner side.
podman exec wakir-spire-server-partner \
    /opt/spire/bin/spire-server bundle set \
    -id spiffe://wakir.test \
    -format jwks \
    -path /var/lib/spire/bundles/wakir.jwks

# Repeat in reverse for the partner.test bundle.
podman exec wakir-spire-server-partner \
    /opt/spire/bin/spire-server bundle list -format jwks \
    > /tmp/partner.jwks
podman cp /tmp/partner.jwks wakir-spire-server-wakir:/var/lib/spire/bundles/partner.jwks
podman exec wakir-spire-server-wakir \
    /opt/spire/bin/spire-server bundle set \
    -id spiffe://partner.test \
    -format jwks \
    -path /var/lib/spire/bundles/partner.jwks
```

Verify the federated bundles are seated on each side:

```bash
podman exec wakir-spire-server-wakir   /opt/spire/bin/spire-server bundle list
podman exec wakir-spire-server-partner /opt/spire/bin/spire-server bundle list
```

Each side's output should now list both its own trust-domain bundle and
the peer's federated bundle. After this manual bootstrap, the live
`https_spiffe` profile fetch takes over as steady-state — SPIRE-Server
refreshes the peer-bundle automatically per the `refresh_hint`.

**X.509-SVID cross-trust verify (Operator-Hand-pendet from sandbox):**
the full SVID-roundtrip (register an entry on side A, fetch an X.509-SVID
on side A's agent, present it to a workload on side B, verify the SVID
chains to side B's federated-bundle-set entry for side A's trust-domain)
is the live-gated test slot. The sandbox does not have podman-host
socket access per `feedback_sandbox_host_trennung.md`; the operator
performs this verify and posts the `spire-server bundle list` output as
the Sprint-8 Tag-1 acceptance evidence.

## 4. Anbindung an Reza-Sprint-7-Tag-3 Cross-Trust-Domain-Bridge

Reza's `wirelang/federation/spiffe_cross_trust_domain_bridge.py` defines
two Protocols this substrate fulfills in live mode:

| Protocol | Substrate impl |
|---|---|
| `PeerTrustBundleFetcher` | HTTPS-fetch against `https://spire-server-<peer>:8443/spire/v1/...` (the bundle-endpoint listener of this substrate). |
| `PeerSvidVerifier` | Verify a peer X.509-SVID against the federated-bundle-set entry seated via the `spire-server bundle set` workflow in §3b. |

The bridge's `LiveBridgeResolution` consumes both Protocols and emits an
accept/reject verdict over a peer SVID. The hermetic test surface in
`wirelang/tests/test_spiffe_cross_trust_domain_bridge*.py` injects
Protocol fakes; this substrate is the live impl those Protocols target
once the live HTTPS-fetch impl lands (Phase-2c follow-up — own Quadlet/
compose surface, not in scope for Sprint-8 Tag-1).

## 5. Cross-Review Gates

| Zone | Counterparty | Item | Status |
|---|---|---|---|
| Zone A | Reza (Wirelang) | SPIFFE-trust-domain literal alignment (`wakir.test` + `partner.test` are hermetic-only; Phase-3a production literal `<FTD-ID>.wakir.dev` is unchanged). | Tag-1 hermetic — no Phase-3a literal touched. |
| Zone B | Reza (NATS-Schema) | None — federation substrate does NOT use NATS. The `multi-org-attestation-nats-kv-backend` (Reza Sprint-7 Tag-2) is unaffected. | Tag-1 unaffected. |
| Zone C | Tomás (Container-Image-Pipeline × OTS-Anchoring) | Cosign-Digest-Pin placeholder `DIGEST_PENDING_TOMAS_REVIEW` resolves to the canonical sha256 digest before live bring-up — same Operator-Hand workflow as compose/spire.yaml (Sprint-6 Tag-8 rebase). | Tag-1 hermetic — placeholder preserved. |
| Zone D | Reza (V-904 Identity-Bridge) | Federation substrate is the V-908 Phase-2-3 surface, not V-904 (Phala-Cloud). No overlap with V-904 Annex Gate. | Not applicable. |

## 6. Hermetic test surface

```bash
# From the repo root:
pytest infra/spire/federation/tests/ -v
```

Three test files; all hermetic (compose-parse + CLI-roundtrip + Quadlet
byte-precision parity). None of them touch podman or pull images. The
Sprint-8 Tag-1 acceptance is **green hermetic test surface + this README
shipped; live cross-trust SVID verify is Operator-Hand-pendet**.

## 7. Known follow-ups (Phase-2c / Sprint-9+)

* **Live HTTPS-fetch impl of `PeerTrustBundleFetcher`** — the bridge in
  `wirelang/federation/spiffe_cross_trust_domain_bridge.py` declares the
  Protocol; this substrate provides the listener. The HTTPS-client
  impl that calls into Wirelang's `LiveBridgeResolution` is a separate
  module (likely `wirelang/federation/spire_bundle_endpoint_fetcher.py`)
  — Reza-track, not Kai-track.
* **Refresh-hint cadence tuning** — SPIRE-Server default refresh-hint
  is 5 min; production cadence may be longer to reduce HTTPS-load.
  Phase-3a tune slot.
* **DataStore migration sqlite3 → postgres** — Phase-3a path.
* **Trust-Bundle-Rotation drill on the federation surface** — the
  Sprint-6 Tag-12 rotation runbook covers the single-server case; the
  federation case needs a dedicated drill (`refresh_hint` re-fetch
  forces peer-side to re-cache).
* **K8s-native equivalent** — Phase-3 Helm-chart for K8s consumers
  (ADR-0020 Box-5).

---
*— Kai*
