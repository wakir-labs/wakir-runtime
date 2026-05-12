# SPIRE-Agent Sidecar — Phase-2.2 Hermetic Skizze (Sprint-6 Tag-9)

This document describes the **Phase-2.2 SPIRE-Agent-Sidecar** substrate
added to `compose/spire.yaml` in Sprint-6 Tag-9. It is the paired
companion to the Phase-2.1 SPIRE-Server-Sidecar documented in
`docs/spire-server-phase-2-1.md`.

**Hermetic-only**: the Tag-9 substrate exercises the compose-shape and
config-shape only. No live SVID is issued. Live-gated bring-up + SVID
fetch is a Phase-2.3 Operator-Hand slot (see §5).

## 1. Substrate components

| Component | Path | Owner | Tag |
|---|---|---|---|
| SPIRE-Agent compose service block | `compose/spire.yaml` (services.spire-agent) | Kai | Tag-9 |
| Agent Mock/Stub config | `config/spire-agent.conf` | Kai | Tag-9 |
| Hermetic acceptance tests | `tests/orchestrator/test_compose_spire_agent.py` | Kai | Tag-9 |
| Workload-API socket-share volume | `spire_agent_sockets` (named) | Kai | Tag-9 |
| Server-Admin-API socket-share volume | `spire_server_sockets` (named, Tag-6) | Kai | Tag-6 (reused) |

The SPIRE-Server side is unchanged from the Tag-8 rebase
(`compose/spire.yaml` services.spire-server, `config/spire-server.conf`,
`tests/orchestrator/test_compose_spire.py`,
`tests/orchestrator/test_compose_spire_cosign_pin.py`).

## 2. Volume topology

Two named volumes carry SPIRE socket traffic:

### 2.1 `spire_server_sockets` — Server-Admin-API channel

Server mount: `/run/spire/sockets`
Agent mount:  `/run/spire/sockets`

This is the gRPC channel the SPIRE-Server exposes for its Admin-API.
The SPIRE-Agent dials this socket-path inside its container namespace
to perform NodeAttestation and registration-entry fetches.

This is the volume Mira's box-brief calls out by name:

> "Workload-API-Unix-Socket via shared named-Volume
>  `spire_server_sockets` (vorausgeplant in Tag-6)"

Strictly speaking, the SPIRE *Server* does not serve the
Workload-API; the SPIRE *Agent* does. The Tag-6 volume `spire_server_
sockets` is therefore the **Server-Admin** socket-share channel
(server-side). The Workload-API-proper lives on a separate volume
(see §2.2). Both volumes carry SPIRE-protocol Unix sockets, hence the
generic "socket-share volume" language in the Tag-6 header.

### 2.2 `spire_agent_sockets` — SPIFFE-Workload-API channel

Agent mount: `/run/spire/agent-sockets`
Persona-container mount (Phase-2.3+): `/run/spire/agent-sockets:ro`

The SPIRE-Agent serves the **SPIFFE-Workload-API** on a Unix-socket at
`/run/spire/agent-sockets/api.sock` (file inside the volume-dir).
Phase-2.3+ persona-containers mount this volume read-only and connect
via the upstream `spiffe` PyPI package (or, more precisely, via the
wirelang adapter — see §4).

### 2.3 `spire_agent_data` — Agent state cache

Agent mount: `/var/lib/spire/agent`

Holds the bootstrap trust-bundle cache, SVID cache, and (in
disk-KeyManager mode) the agent's key material. The Tag-9 hermetic
substrate uses the **in-memory KeyManager** so a `compose down/up`
cycle forces re-attestation; the data-volume is shape-only.

`compose down -v` drops this volume deliberately.

## 3. Trust-domain pin

Both server and agent declare `trust_domain = "example.test"` — the
IANA-reserved test TLD (RFC 6761 §6.5). This is the **hermetic-only
marker**: an operator who sees `example.test` in a SPIRE container's
config knows the substrate is not a production stand.

Production trust-domain pins are tracked separately:
- Phase-2 production literal: `wakir.local` (skizze §2).
- Phase-3a federation trust-domain: `<FTD-ID>.wakir.dev`.

Switching the hermetic substrate to a production trust-domain is a
Phase-2.4 NATS-JWT-Auth-integration tag, **not** a Tag-9 change.

## 4. Wirelang-side cross-reference (Reza-track)

Tag-9 is the DevOps-track substrate. The **wirelang-side surface**
that persona-containers consume is owned by Reza:

| Surface | Path | Reza-Sprint-6 Tag | Status in Tag-9 baseline |
|---|---|---|---|
| SPIFFE-ID-Binding spec | `wirelang/specs/identity-substrate.md` §5 | Tag-4 (`ece8f45`) | Not yet merged into Tag-9 base |
| Workload-API adapter skeleton | `wirelang/adapters/spiffe_workload_api.py` | Tag-4 (skeleton), Tag-5 (`9c94517` Mock adapter) | Not yet merged into Tag-9 base |
| Real adapter | `wirelang/adapters/real_spiffe_workload_api.py` | Tag-7+ slot | Not in Sprint-6 Tag-7 yet |
| Test-counts convention | `docs/test-counts-convention.md` | Tag-5 | Not yet merged |

**Tag-9 does not import the Reza adapter** because none of the Reza
Sprint-6 Tag-4/Tag-5 commits are in the Tag-9 baseline (`origin/kai/
phase-2-sprint-6-tag-8-rebase-cosign-pin` = `8a6e5ad`). The Tag-9
hermetic substrate is autark — it asserts only compose-/HCL-shape
invariants on its own files. Phase-2.3+ persona-container consumers
will pick up the Reza adapter once both tracks land in a common base
(coordination via Aisha + Priya).

The SPIFFE-ID path-pattern that the Reza spec defines
(`spiffe://example.test/agent/<persona-slug>/<persona-hash-12>` for
persona-mint workloads; `spiffe://example.test/service/<service-name>`
for service-only workloads) is **compatible** with the Tag-9 substrate
without modification — the trust-domain matches, and the Tag-9
substrate makes no claim about per-workload SPIFFE-ID structure (that
is a Phase-2.3 registration-entry generator's responsibility).

## 5. Operator-Hand items (Phase-2.3+)

The Tag-9 substrate is hermetic. Live bring-up is **Operator-Hand**:

### 5.1 Cosign-digest substitution

The agent image-pin (and the server image-pin from Tag-8) carry the
placeholder digest `DIGEST_PENDING_TOMAS_REVIEW`. Operator-Hand
workflow:

```sh
# Verify the SPIRE-Agent image with cosign.
cosign verify \
    --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/spiffe/spire-agent:1.14.6

# Resolve the canonical digest with skopeo.
skopeo inspect docker://ghcr.io/spiffe/spire-agent:1.14.6 \
    | jq -r '.Digest'

# Substitute the placeholder with the canonical 64-hex digest.
sed -i 's/spire-agent:1.14.6@sha256:DIGEST_PENDING_TOMAS_REVIEW/spire-agent:1.14.6@sha256:<digest>/' \
    compose/spire.yaml

# Commit.
git commit -am "chore(spire): pin spire-agent image to sha256:<short>"
```

Prerequisite: Tomás Zone-C acknowledgement for the Tag-9 image-pin
(co-pilot with the Tag-8 server-side Zone-C ack — see
`dev-engineering/inbox/2026-05-12-zone-c-cross-review-spire-server-image-pin.md`).

### 5.2 Join-token issuance (live bring-up)

```sh
# On the host, with the SPIRE-Server already running:
docker compose -f compose/spire.yaml exec spire-server \
    /opt/spire/bin/spire-server token generate \
    -spiffeID spiffe://example.test/agent/wakir-test

# Pass the resulting token to the SPIRE-Agent at startup
# (override the compose command):
docker compose -f compose/spire.yaml run --rm \
    --entrypoint /opt/spire/bin/spire-agent spire-agent \
    run -config /etc/spire/agent/agent.conf -joinToken <token>
```

This is the Phase-2 manual-enrollment flow. Phase-3+ swaps to a
trust-bundle-pre-staged form (`insecure_bootstrap = false`).

### 5.3 SVID fetch live-smoke (Phase-2.3 follow-up)

```sh
# Inside the agent container (or a persona-container with the
# spire_agent_sockets volume mounted read-only):
docker compose -f compose/spire.yaml exec spire-agent \
    /opt/spire/bin/spire-agent api fetch jwt \
    -socketPath /run/spire/agent-sockets/api.sock \
    -audience wakir-orchestrator
```

A successful JWT-SVID fetch with `aud=wakir-orchestrator` is the
Phase-2.3 acceptance signal. This is **gated on**: (a) Tomás Zone-C
ack for both image-pins (server + agent), (b) Operator-Hand digest
substitution done, (c) a host with podman/docker + cosign + skopeo
available.

## 6. Bring-up + tear-down (hermetic)

```sh
# Hermetic compose-shape acceptance (no live SVIDs):
pytest tests/orchestrator/test_compose_spire_agent.py
pytest tests/orchestrator/test_compose_spire.py
pytest tests/orchestrator/test_compose_spire_cosign_pin.py
```

These three test files cover 45 invariants (16 Tag-6 + 9 Tag-8 + 20
Tag-9). All pass at the Tag-9 tip on hermetic CI.

Live bring-up (Operator-Hand, after Cosign-digest substitution):

```sh
docker compose -f compose/spire.yaml up -d
docker compose -f compose/spire.yaml down -v   # -v drops the volumes
```

## 7. Drift-detection invariants

The Tag-9 test suite catches drift on:

| Drift | Caught by |
|---|---|
| Agent and server trust-domain de-sync | `test_agent_and_server_conf_share_same_trust_domain` |
| Workload-API socket-path filename change | `test_agent_conf_pins_workload_api_socket_path` |
| Agent NodeAttestor switch away from join_token (no paired Phase-3 ADR) | `test_agent_conf_declares_join_token_node_attestor` |
| Agent image pulled without Cosign-digest pin | `test_agent_image_has_cosign_digest_pin_form` |
| Hardening regression (cap_drop / read_only / no-new-priv / non-root) | `test_agent_has_hardening_parity_with_server` |
| Server-admin-socket volume drift between server and agent | `test_agent_mounts_server_admin_sockets_volume` |
| Workload-API volume placed on the server side by accident | `test_agent_serves_workload_api_on_dedicated_volume` |
| Compose v2 `depends_on` reverted to short-form (silent-pass gotcha) | `test_agent_depends_on_server_with_health_gate` |
| SPIRE version skew between server and agent | `test_agent_pinned_tag_matches_server_version` |

## 8. Follow-up slots

- **F-1 (Tag-8 carry-over):** Operator-Hand digest-substitution for the
  SPIRE-Server image (pending Tomás Zone-C ack).
- **F-1' (new, Tag-9):** Operator-Hand digest-substitution for the
  SPIRE-Agent image (paired with F-1; same Tomás Zone-C cross-review).
- **F-4 (Tag-8 trigger satisfied by Tag-9):** Phase-2.2 SPIRE-Agent-
  Sidecar — this is Tag-9 itself. The further Phase-2.3 SVID-fetch
  live-smoke is Operator-Hand and listed under §5.3.
- **F-5 (Tag-8 carry-over):** WAT-Aggregator-Test-Isolation-Drift —
  Tomás-Hand. Three tests in `tests/wat/test_aggregator_prev_hour_root.py`
  fail in the wakir-runtime clone but not in the /tmp-worktree clone.
  Still present in the Tag-9 baseline; not a Tag-9 regress.
- **Phase-2.3 SVID-fetch live-smoke:** Operator-Hand bring-up + SVID
  fetch round-trip. Gated on F-1 + F-1' Tomás-ack.
- **Phase-2.4 NATS-JWT-Auth integration:** SPIRE-Agent issues
  JWT-SVIDs that the NATS-Server's `nats-jwt` auth-callout
  validates. Trust-domain switches from `example.test` to
  `wakir.local`.
- **Phase-2c Disk-KeyManager:** Switch agent KeyManager from `memory`
  to `disk` so the agent retains identity across compose-restart.
- **Phase-3a x509pop NodeAttestor:** Replace `join_token` with
  `x509pop` for federation-grade attestation; remove `insecure_
  bootstrap`.

— Kai
