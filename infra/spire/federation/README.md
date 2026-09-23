# SPIRE-Federation-Bundle-Endpoint

**Status:** Hermetic substrate. Live bring-up is Operator-Hand per
[`feedback_sandbox_host_trennung.md`][sandbox-trennung]. The sandbox does
NOT touch the host's podman socket.

[sandbox-trennung]: ../../../../.claude/feedback_sandbox_host_trennung.md

This directory carries the SPIRE-Federation-
Bundle-Endpoint substrate: two SPIRE-Server containers in two distinct
hermetic trust-domains (`wakir.test` and `partner.test`), wired so each
server's federation-bundle-endpoint listener is reachable to the other's
HTTPS-SPIFFE-profile peer-fetch. Substrate is the live counterpart to
the SPIFFE-Cross-Trust-Domain-Bridge
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
| `bin/spire-fed-bundle` | **Fixture only.** Bundle Export/Import CLI over hermetic-fixture JWKS. Not a bootstrap-anchor stager — see §3c. |
| `bin/spire_fed_bundle.py` | **Fixture only.** CLI module (import target for tests). |
| `bin/spire-fed-bundle-rotator` | **Fixture only.** Bundle-Rotation CLI over fixture JWKS. Not a bootstrap-anchor stager — see §3c. |
| `bin/spire_fed_bundle_rotator.py` | **Fixture only.** Rotator CLI module (import target for tests). |
| `bin/spire-fed-health` | Federation Health-Check HTTP-server. |
| `bin/spire_fed_health.py` | Health-server module (import target for tests). |
| `bin/spire-fed-metrics` | Federation Prometheus-text-format metrics surface. |
| `bin/spire_fed_metrics.py` | Metrics-server module (import target for tests). |
| `IMAGE_PINS.md` | Cosign-Digest-Pin resolution index. |
| `quadlet/wakir-spire-server-federation.container` | Quadlet template (placeholders for `<SIDE>`, `<HOST_BUNDLE_PORT>`, `<HOST_GRPC_PORT>`, `<HOST_BUNDLE_BIND>` — last one parametrises bundle-endpoint host bind per for Cross-VM federation). |
| `quadlet/wakir-federation.network` | Quadlet bridge-network sidecar. |
| `bin/wakir-spire-stage-bootstrap-anchor` | Live bootstrap-anchor stager (§3c). The one that writes a real anchor. |
| `quadlet/wakir-spire-server-federation-{data,sockets,bundles,upstream-ca}.volume` | Quadlet named-volume sidecars (per-side via placeholder). |
| `quadlet/wakir-spire-bootstrap-anchor-restage.{service,timer}` | Plain systemd units (not Quadlet) that re-run the stager below `ca_ttl`. |
| `tests/test_federation_compose.py` | Hermetic compose-shape + config-shape invariants. |
| `tests/test_spire_fed_bundle_cli.py` | Hermetic CLI roundtrip + trust-domain mismatch guard. |
| `tests/test_federation_quadlet.py` | Compose ↔ Quadlet byte-precision parity. |
| `tests/test_spire_fed_bundle_rotator.py` | Rotation-Lifecycle: soft-cutover, hard-revoke, grace-window, cross-TD-isolation, determinism. |
| `tests/test_spire_fed_health.py` | Health-server: /live, /health, /ready, schema, rotation-mid-state. |
| `tests/test_spire_fed_metrics.py` | Metrics-server: counters, gauges, Prometheus text-format, determinism. |
| `tests/test_image_pin_digest_form.py` | Image-pin syntax invariants: server-agent version-parity, atomic resolution state. |

## 1. Compose substrate

Two SPIRE-Server containers on a dedicated `wakir-federation` bridge
network (isolated from the `wakir-orchestrator` network). Each
server's bundle-endpoint listener binds container port `8443`. Host
port-publish (hermetic same-host topology):

| Side | Bundle-endpoint (host) | gRPC API (host) | Container |
|---|---|---|---|
| `wakir.test` | `127.0.0.1:8443` | `127.0.0.1:8082` | `wakir-spire-server-wakir` |
| `partner.test` | `127.0.0.1:8444` | `127.0.0.1:8083` | `wakir-spire-server-partner` |

The two containers reach each other over the bridge network's internal
DNS (`spire-server-wakir`, `spire-server-partner`), NOT over the host's
loopback. Host port-publish is loopback-only and exists for operator
introspection during bring-up.

** Cross-VM federation extension:** for a Pilot-VM
running in `WAKIR_PILOT_MODE=federation` (Cross-VM M-3 Live-Trial),
the Quadlet bundle-endpoint publishes on `0.0.0.0:8443` instead of
`127.0.0.1:8443` so a peer VM can fetch the bundle. The gRPC API
(`127.0.0.1:8082`) stays loopback-only in BOTH modes — security
invariant. See `PARTNER_VM_BRING_UP_RECIPE.md` §5 for the exact
bootstrap-env-var sequence (`WAKIR_PILOT_MODE=federation`,
`WAKIR_PEER_SIDE`, `WAKIR_PEER_HOST`).

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

The acceptance is the cross-trust-domain bundle
roundtrip. Two variants:

> **The `spire-fed-bundle` CLIs in §3a and §7 are fixtures, not tools.**
> They emit well-formed JWKS whose keys are **not** SPIRE CA keys. They
> exist to exercise the export/import/rotate shapes hermetically. If you
> point one of them at an agent's `trust_bundle_path`, you get a file in
> the right place, a green check, and an agent that still cannot attest —
> the exact failure this substrate spent 127 days in. The live path is
> §3c and nothing else. (ADR-0076, context finding (c).)

### 3a. Hermetic CLI roundtrip (sandbox-safe)

Runs against the `spire-fed-bundle` CLI with hermetic-fixture JWKS —
no SPIRE-Server, no podman, no live. The
`tests/test_spire_fed_bundle_cli.py` suite exercises this end-to-end.
**Fixture surface. Its output never reaches a live agent.**

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
the acceptance evidence.

### 3c. Bootstrap trust anchor — the live staging path (ADR-0076)

§3a is a fixture. §3b is the *peer* bundle exchange. This section is the
third thing, and it is the one that was missing for 127 days: the
agent's **own** bootstrap anchor.

Both agent configs declare

```hcl
trust_bundle_path = "/var/lib/spire/bundles/bootstrap.jwks"
```

and nothing ever wrote that file. Measured on both pilot VMs
2026-09-22: the directory exists, is empty, and has been empty since it
was created in May. The agent ran off the bundle cache in its own data
volume until the cache aged out under the 24h `ca_ttl`, then stopped
attesting. No alarm fired, because nothing was looking.

Two mechanisms, both installed by `wakir-pilot-bootstrap.sh` in
federation mode:

**The root** (`UpstreamAuthority "disk"`, step 6g-bis). The bootstrap
creates a self-signed EC P-256 root with a multi-year lifetime into the
per-side `-upstream-ca` volume (`root.crt` 0644, `root.key` 0600, uid
1000) and the server mints its daily signing intermediates against it.
The material is created **once** and never regenerated by a re-run; a
half-present pair aborts the bootstrap instead of healing itself,
because replacing the root invalidates every SVID and every bundle copy
on **both** federation sides. That is a bilateral maintenance-window
cutover (ADR-0076 §Migration), not a bring-up step.

**The anchor** (`bin/wakir-spire-stage-bootstrap-anchor`, step 6h-bis).
Between server start and agent start the bootstrap runs

```bash
/var/lib/wakir/bin/wakir-spire-stage-bootstrap-anchor --side <side>
```

which reads `spire-server bundle show -format spiffe` from the running
server via `podman exec`, decides whether the document is an anchor,
writes it to a temp file in the target directory and renames it into
place, then reads it back and stat-verifies mode and owner.

**What counts as an anchor** (sharpened after the Zone-L cross-review of
PR #561): not "at least one key". A bundle holding one `jwt-svid` key and
no X.509 authority passed the old key count, staged green, and left a
real SPIRE-Agent v1.14.6 answering `no certificates found in trust
bundle` in an endless retry loop. The document must carry

1. at least one entry with `use == "x509-svid"` and a non-empty `x5c`,
   and
2. among those, the certificate of **our** upstream CA root
   (`/var/lib/spire/upstream-ca/root.crt`). `x5c` is base64 DER and a PEM
   file is base64 DER between two armour lines, so the comparison needs
   no crypto and no new dependency.

(2) also rejects a fixture JWKS from the `spire-fed-bundle` CLIs in this
directory and the peer side's bundle staged into our own volume. "At
least one" and not "all", because during a bilateral root cutover the
bundle legitimately carries the old and the new root at once.

**The decider is a real JSON parser** — `python3` when present, otherwise
`jq` in `--slurp` mode; the dependency-free shape check is a pre-check
only. `--slurp` matters: plain `jq` reads a *stream* of JSON values, so a
document emitted twice parses cleanly. When neither parser is on PATH the
stager exits **3** and stages nothing; it does not fall back to a weaker
check.

Exit codes: `0` staged and verified · `2` read, and not an anchor · `3`
could not decide (no parser, or the upstream root unreadable). Both
failure classes leave the previous anchor untouched and print the
diagnosis the failing command itself produced. There is no branch on
which the script exits 0 without a verified file on disk.

`wakir-spire-bootstrap-anchor-restage-<side>.timer` re-runs the same
script every 30 minutes. `ca_ttl` stays at 24h by decision, so the
signing intermediate keeps rotating daily and a once-staged anchor
would reproduce the May half-life.

Operator check, on the node:

```bash
# The anchor exists, is non-empty, and is owned by the container user.
BUNDLES=$(sudo podman volume inspect --format '{{.Mountpoint}}' \
            wakir-spire-server-federation-<SIDE>-bundles)
sudo ls -l "$BUNDLES/bootstrap.jwks"

# The timer is armed and has run.
systemctl list-timers 'wakir-spire-bootstrap-anchor-restage-*'
systemctl status wakir-spire-bootstrap-anchor-restage-<SIDE>.service
```

**Known limit, stated rather than left to be found.** The stager
verifies DAC — content, mode `0644`, owner `1000:1000`. It does not
verify that the agent's SELinux context may read the file. The bundles
volume is mounted `Z` (private relabel) by the server and `ro,Z` by the
agent; two private relabels of one volume is a posture that wants a
measurement on an enforcing node, and it has not had one. If the agent
reports `permission denied` on `trust_bundle_path` while the file is
visibly present and correctly owned, look there first.

## 4. Anbindung an Cross-Trust-Domain-Bridge

the `wirelang/federation/spiffe_cross_trust_domain_bridge.py` defines
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
compose surface, not in scope here).

## 5. Cross-Review Gates

| Zone | Counterparty | Item | Status |
|---|---|---|---|
| Zone A | Wirelang | SPIFFE-trust-domain literal alignment (`wakir.test` + `partner.test` are hermetic-only; Phase-3a production literal `<FTD-ID>.wakir.dev` is unchanged). | hermetic — no Phase-3a literal touched. |
| Zone B | NATS-Schema | None — federation substrate does NOT use NATS. The `multi-org-attestation-nats-kv-backend` is unaffected. | unaffected. |
| Zone C | Container-Image-Pipeline × OTS-Anchoring | Cosign-Digest-Pin placeholder `DIGEST_PENDING_TOMAS_REVIEW` resolves to the canonical sha256 digest before live bring-up — same Operator-Hand workflow as compose/spire.yaml (Pfad-B rebase). | hermetic — placeholder preserved. |
| Zone D | V-904 Identity-Bridge | Federation substrate is the V-908 Phase-2-3 surface, not V-904 (Phala-Cloud). No overlap with V-904 Annex Gate. | Not applicable. |

## 6. Hermetic test surface

```bash
# From the repo root:
pytest infra/spire/federation/tests/ -v
```

Four test files (adds the rotator suite); all hermetic (compose-
parse + CLI-roundtrip + Quadlet byte-precision parity + rotation-
lifecycle). None of them touch podman or pull images. The
The acceptance is **green hermetic test surface + this README §7
shipped; live cross-trust SVID verify and live rotation drill are
Operator-Hand-pendet**.

## 7. Rotation

> **Fixture surface.** This section describes the rotation *lifecycle
> shape* over fixture JWKS. It is not the live bootstrap-anchor
> refresh. That is §3c's stager on a 30-minute timer, and it is the
> only mechanism whose output a running agent reads.

The substrate adds the time-driven JWKS rotation surface on top
of the static bundle endpoint. The lifecycle has four operator-
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
OLD_KID="spiffe://wakir.test/spire/server/fixture-key" # base kid
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

## 8.: Health + Metrics + Cosign-Digest-Pin

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

The `--agent-connections` value is operator-provided for now; Phase-
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
(gated on image-pipeline cross-review for the GHCR network egress
policy).

## 9. Known follow-ups (Phase-2c)

* **Live HTTPS-fetch impl of `PeerTrustBundleFetcher`** — the bridge in
  `wirelang/federation/spiffe_cross_trust_domain_bridge.py` declares the
  Protocol; this substrate provides the listener. The HTTPS-client
  impl that calls into Wirelang's `LiveBridgeResolution` is a separate
  module (likely `wirelang/federation/spire_bundle_endpoint_fetcher.py`)
  — identity-substrate track, not infra track.
* **Refresh-hint cadence tuning** — SPIRE-Server default refresh-hint
  is 5 min; production cadence may be longer to reduce HTTPS-load.
  Phase-3a tune slot.
* **DataStore migration sqlite3 → postgres** — Phase-3a path.
* **Trust-Bundle-Rotation drill on the federation surface** —
  hermetic substrate in place (§7). The live-
  bring-up rotation drill (Operator-Hand on the host SPIRE-Server
  with native `bundle set`) is the next step; the recipe is in §7.
* **K8s-native equivalent** — Phase-3 Helm-chart for K8s consumers
  (ADR-0020 Box-5).

---
