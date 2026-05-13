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
| `bin/spire-fed-bundle-rotator` | Bundle-Rotation CLI (Tag-3). |
| `bin/spire_fed_bundle_rotator.py` | Rotator CLI module (import target for tests). |
| `bin/spire-fed-health` | Federation Health-Check HTTP-server (Tag-4). |
| `bin/spire_fed_health.py` | Health-server module (import target for tests). |
| `bin/spire-fed-metrics` | Federation Prometheus-text-format metrics surface (Tag-4). |
| `bin/spire_fed_metrics.py` | Metrics-server module (import target for tests). |
| `IMAGE_PINS.md` | Cosign-Digest-Pin resolution index (Tag-4). |
| `quadlet/wakir-spire-server-federation.container` | Quadlet template (placeholders for `<SIDE>`, `<HOST_BUNDLE_PORT>`, `<HOST_GRPC_PORT>`). |
| `quadlet/wakir-federation.network` | Quadlet bridge-network sidecar. |
| `quadlet/wakir-spire-server-federation-{data,sockets,bundles}.volume` | Quadlet named-volume sidecars (per-side via placeholder). |
| `tests/test_federation_compose.py` | Hermetic compose-shape + config-shape invariants. |
| `tests/test_spire_fed_bundle_cli.py` | Hermetic CLI roundtrip + trust-domain mismatch guard. |
| `tests/test_federation_quadlet.py` | Compose ↔ Quadlet byte-precision parity. |
| `tests/test_spire_fed_bundle_rotator.py` | Rotation-Lifecycle (Tag-3): soft-cutover, hard-revoke, grace-window, cross-TD-isolation, determinism. |
| `tests/test_spire_fed_health.py` | Health-server (Tag-4): /live, /health, /ready, schema, rotation-mid-state. |
| `tests/test_spire_fed_metrics.py` | Metrics-server (Tag-4): counters, gauges, Prometheus text-format, determinism. |
| `tests/test_image_pin_digest_form.py` | Image-pin syntax invariants (Tag-4): server-agent version-parity, atomic resolution state. |

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

Four test files (Tag-3 adds the rotator suite); all hermetic (compose-
parse + CLI-roundtrip + Quadlet byte-precision parity + rotation-
lifecycle). None of them touch podman or pull images. The Sprint-8
Tag-3 acceptance is **green hermetic test surface + this README §7
shipped; live cross-trust SVID verify and live rotation drill are
Operator-Hand-pendet**.

## 7. Rotation (Phase-2 Sprint-8 Tag-3)

The Tag-3 substrate adds the time-driven JWKS rotation surface on top
of the Tag-1 static bundle endpoint. The lifecycle has four operator-
hand steps wired through the `spire-fed-bundle-rotator` CLI:

| Step | CLI | Trigger | Cron-cadence (recommended) |
|---|---|---|---|
| 1. Rotate | `spire-fed-bundle-rotator rotate` | Operator-hand, planned cadence | Daily (24h CA-rotation drift) |
| 2. Distribute | `podman cp` rotated JWKS → peer | Operator-hand | Immediate after step 1 |
| 3. Peer-reload | `spire-agent-fed-reload poll-once` (cron 1h) OR `podman kill --signal HUP <agent>` | Peer-side, automatic OR SIGHUP | 1h default |
| 4. Expire | `spire-fed-bundle-rotator expire` | Operator-hand, after grace-window | Daily, T+24h after step 1 |

### Operator-Hand recipe (canonical rotation drill)

```bash
cd infra/spire/federation/bin

# Step 1: Rotate at T=now (24h grace-window for the OLD key).
NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
./spire-fed-bundle-rotator rotate \
    --trust-domain wakir.test \
    --in-file /tmp/wakir.jwks \
    --out /tmp/wakir-v2.jwks \
    --now "$NOW" \
    --grace-seconds 86400

# Inspect the result: should show one 'valid' (new) + one 'grace' (old).
./spire-fed-bundle-rotator list \
    --in-file /tmp/wakir-v2.jwks \
    --now "$NOW"

# Step 2: Distribute (atomic write-temp-then-rename on the peer side).
podman cp /tmp/wakir-v2.jwks \
    wakir-spire-server-partner:/var/lib/spire/bundles/wakir.jwks.new
podman exec wakir-spire-server-partner \
    mv /var/lib/spire/bundles/wakir.jwks.new \
       /var/lib/spire/bundles/wakir.jwks

# Step 3: Peer-side agent re-reads the bundle. Either wait for the
# cron-cycle (default 1h) or trigger immediately:
podman kill --signal HUP wakir-spire-agent-partner

# Step 4 (T+24h, after grace-window): expire the OLD key.
EXPIRE_NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
./spire-fed-bundle-rotator expire \
    --trust-domain wakir.test \
    --in-file /tmp/wakir-v2.jwks \
    --out /tmp/wakir-v3.jwks \
    --now "$EXPIRE_NOW"

# Verify the post-grace verify rejects the old kid (sanity check):
OLD_KID="spiffe://wakir.test/spire/server/fixture-key"   # Tag-1 base kid
./spire-fed-bundle-rotator verify \
    --in-file /tmp/wakir-v3.jwks \
    --kid "$OLD_KID" \
    --now "$EXPIRE_NOW"
# Expected exit-code 2 ('kid <...> not in bundle' after expire).
```

### Rotation invariants (hermetic-tested)

* **Soft-cutover**: between step 1 and step 4, both OLD and NEW kids
  verify accepted. A peer-side X.509-SVID signed by either key is
  accepted by the federated agent.
* **Hard-revoke**: after step 4 + a peer-side reload (step 3 re-run),
  the OLD kid no longer verifies. Peer-side X.509-SVIDs signed by
  the OLD key are rejected.
* **Grace-window**: between `--now` of step 1 and step 4, the OLD
  kid carries a `_wakir_not_after` marker. `verify` rejects the
  OLD kid with an explicit `expired` reason once `--now > not_after`.
* **Cross-trust-domain isolation**: rotation of `wakir.test` does NOT
  touch `partner.test` bundles. The rotator refuses to operate on
  a bundle whose hermetic-fixture trust-domain marker does not
  match `--trust-domain`.
* **Determinism**: same inputs (trust-domain, `--now`, grace-seconds,
  base JWKS) yield bit-identical output JWKS. Two rotations with
  identical inputs produce identical files.
* **Empty-bundle guard**: `expire` refuses to leave the bundle with
  zero valid keys. The operator MUST rotate before expiring the
  last remaining key.

### Live SPIRE-Server rotation (Operator-Hand, beyond hermetic scope)

The hermetic rotator operates on the JWKS file format. For live
SPIRE-Server CA rotation, the operator uses SPIRE-Server's native
`bundle set` workflow as described in §3b, but with the rotator-
produced multi-key JWKS as input:

```bash
# Replace the existing federated bundle with the multi-key version.
podman cp /tmp/wakir-v2.jwks \
    wakir-spire-server-partner:/var/lib/spire/bundles/wakir.jwks
podman exec wakir-spire-server-partner \
    /opt/spire/bin/spire-server bundle set \
    -id spiffe://wakir.test \
    -format jwks \
    -path /var/lib/spire/bundles/wakir.jwks
```

The live SPIRE-Server accepts a JWKS with multiple keys and uses
all of them for SVID verification, so the soft-cutover invariant
holds in live mode without additional tooling.

## 8. Tag-4: Health + Metrics + Cosign-Digest-Pin

### 8.1 Health-endpoint (`spire-fed-health`)

Operator-Hand and Prometheus blackbox can introspect the bundle
state without parsing JWKS. The CLI exposes three endpoints over a
configurable bind port (default `127.0.0.1:8444`):

| Path | Purpose | HTTP codes |
|---|---|---|
| `/live` | Liveness only — the endpoint answered → it is alive. | `200` always |
| `/health` / `/healthz` | Full structured status document (readiness + introspection). | `200` healthy / `503` unready / `500` error |
| `/ready` / `/readiness` | Compact readiness probe (single-field body). | same as `/health` |

Status JSON shape (schema_version=1):

```json
{
  "_schema_version": 1,
  "status": "healthy" | "unready" | "error",
  "trust_domain": "wakir.test",
  "active_keys": 2,
  "last_rotation_at": "2026-05-13T01:30:00+00:00",
  "agent_connections": 3,
  "checks": {
    "bundle_present": true,
    "bundle_non_empty": true,
    "active_key_count_ok": true,
    "rotation_error_state": false
  }
}
```

Readiness state mapping:

* `healthy`: bundle present + non-empty + ≥ `--min-active-keys`
  non-expired keys + rotation-error flag not set.
* `unready`: bundle missing/empty/malformed OR insufficient
  non-expired keys.
* `error`: caller signalled `--rotation-error` (rotation system in
  failure mode — operator inspection needed before bring-up
  continues).

Operator-Hand invocation example:

```sh
spire-fed-health \
    --trust-domain wakir.test \
    --bundle-path /var/lib/spire/bundles/wakir.jwks \
    --bind-host 127.0.0.1 \
    --bind-port 8444 \
    --agent-connections 3
```

The `--agent-connections` value is operator-provided in Tag-4; Phase-
2c+ wires it from the SPIRE-Agent Workload-API admin counter.

### 8.2 Metrics-endpoint (`spire-fed-metrics`)

Prometheus 0.0.4 text-format on a separate bind port (default
`127.0.0.1:8445`):

| Metric | Type | Labels |
|---|---|---|
| `wakir_federation_bundle_cache_hits_total` | counter | `trust_domain` |
| `wakir_federation_bundle_cache_misses_total` | counter | `trust_domain` |
| `wakir_federation_rotation_events_total` | counter | `trust_domain`, `type` ∈ `rotate`/`expire`/`cross-td-refuse` |
| `wakir_federation_active_keys` | gauge | `trust_domain` |
| `wakir_federation_agent_connections` | gauge | `trust_domain` |

Gauges are read on each scrape from the JWKS bundle on disk (no
caching). Counters are in-process additive — the rotation
orchestration code holds a reference to the `MetricsRegistry` and
calls `increment_*` for each lifecycle event.

Empty-initial-state invariant: a freshly-constructed registry
exposes ALL metric NAMES with value 0 (Prometheus convention — no
silently-missing metrics).

Operator-Hand smoke-check:

```sh
spire-fed-metrics \
    --trust-domain wakir.test \
    --bundle-path /var/lib/spire/bundles/wakir.jwks \
    --bind-port 8445 \
    --agent-connections 3 &

curl -s http://127.0.0.1:8445/metrics | grep wakir_federation_
```

`spire-fed-metrics --render-once` skips the HTTP server and prints
the text-format directly to stdout (hermetic-test surface + manual
inspection).

### 8.3 Cosign-Digest-Pin

The image-pins for `ghcr.io/spiffe/spire-server:1.14.6` and
`ghcr.io/spiffe/spire-agent:1.14.6` still carry the placeholder
`DIGEST_PENDING_TOMAS_REVIEW`. The resolution recipe — including the
canonical `cosign verify` invocation, the parity-check via skopeo /
crane, and the multi-file `sed` substitution — is documented in
[`IMAGE_PINS.md`](IMAGE_PINS.md).

The hermetic test
[`tests/test_image_pin_digest_form.py`](tests/test_image_pin_digest_form.py)
enforces SYNTAX invariants on the four pinned files:

* Canonical reference form `ghcr.io/spiffe/spire-{server,agent}:<tag>@sha256:<digest>`.
* Server-agent tag version-parity (both pinned to `1.14.6`).
* Atomic digest-resolution state across all four files (no
  half-resolved state).
* IMAGE_PINS.md index file references each pinned file by name.

Live `cosign verify` is **Operator-Hand** per
[`feedback_sandbox_host_trennung.md`][sandbox-trennung]; the sandbox
does NOT touch GHCR. A CI activation sketch is in IMAGE_PINS.md §3
(gated on Tomás Zone-C cross-review for the GHCR network egress
policy).

## 9. Known follow-ups (Phase-2c / Sprint-9+)

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
* **Trust-Bundle-Rotation drill on the federation surface** —
  hermetic substrate in place as of Sprint-8 Tag-3 (§7). The live-
  bring-up rotation drill (Operator-Hand on the host SPIRE-Server
  with native `bundle set`) is the next step; the recipe is in §7.
* **K8s-native equivalent** — Phase-3 Helm-chart for K8s consumers
  (ADR-0020 Box-5).

---
*— Kai*
