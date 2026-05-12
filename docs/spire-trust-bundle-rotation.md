# SPIRE Trust-Bundle-Rotation Operator-Runbook (Phase-2.6)

**Status:** Operator-Hand. Phase-2.6 runbook substance per the
SPIFFE Z-A skizze §9 phase-plan and §10 risk-row "Trust-Bundle-
Rotation-Sequence" (DevOps-track Operations, no Wirelang-side
block; Reza-Z-A-Ack-Slot-4 §4.4).

**Cross-Reference:** SPIFFE-Skizze §4.2 (Sequenz-Schritte
Phase-2-Boot, `docs/spiffe-z-a-jwt-svid-skizze.md`) is the
canonical reference for the bootstrap-sequence the rotation steps
inherit from.

**Authoring-Zeitstempel:** `date -u 2026-05-12T18:47:56Z` (CEST
20:47, Phase-2 Sprint-6 Tag-11).

**Scope:** This runbook covers the Phase-2 hermetic substrate's
trust-bundle-rotation sequence. Live-host execution is operator-
hand per ADR-0051 (Mira-Sandbox-vs-Host-Operations-Trennung); the
sandbox MUST NOT perform real podman/systemd operations and MUST
NOT call into a live SPIRE-Server.

---

## 1. Why rotate the trust-bundle?

The SPIRE-Server signs JWT-SVIDs and X.509-SVIDs with a CA whose
public key is published as the **trust-bundle**. NATS-Server (with
JWT-Auth from Phase-2.4 enabled) validates every CONNECT-frame JWT
against this trust-bundle. The bundle rotates for three reasons:

1. **CA-rotation-cadence.** SPIRE upstream's boring-default is a
   24-hour upstream-CA TTL with a 1-hour intermediate-CA TTL. The
   intermediate rotates automatically; the upstream CA does not.
   Operator-Hand rotates the upstream CA on a documented schedule
   (Phase-2 default: 30 days; Phase-3 trigger: live-incident or
   compromise).
2. **Trust-domain migration.** Phase-2 trust-domain is the IANA-
   reserved `example.test`. Phase-3a switch to the federation
   trust-domain `<FTD-ID>.wakir.dev` (V-908 federation pattern)
   invalidates every Phase-2 bundle.
3. **Compromise response.** A leaked CA private key forces an
   emergency rotation. Phase-2.6 does not yet cover incident-
   response timelines; this is a Phase-3-trigger slot.

This runbook covers cases (1) and (2). Case (3) inherits the
mechanics but adds the compromise-response timeline as an
addendum-slot (see §7).

---

## 2. Pre-Conditions

Before starting a rotation:

- [ ] **SPIRE-Server is running and healthcheck-green.** Confirm
      with `podman healthcheck run wakir-spire-server` (or
      `systemctl status wakir-spire-server.service` on Quadlet).
- [ ] **SPIRE-Agent is running and healthcheck-green.** Confirm
      with `podman healthcheck run wakir-spire-agent`.
- [ ] **Trust-bundle expiry watch.** Operator has recorded the
      current upstream-CA `not_after` timestamp. The default
      Phase-2 expiry-watch trigger is `not_after - 7 days`.
- [ ] **Cross-Review Zone-A consensus recorded.** If the rotation
      changes the trust-domain (case 2), Aisha-Marker-Recording
      for the trust-domain switch must be present.
- [ ] **Backup of current trust-bundle.** `cosign verify`-
      compatible signed copy of the bundle in
      `/var/lib/wakir/spire/bundles/<timestamp>.pem` so a
      roll-back path is available.
- [ ] **NATS-JWT-Auth phase marker.** If Phase-2.4 NATS-JWT-Auth
      is active (operator-hand bring-up beyond the hermetic
      substrate), the NATS-Server config must be reachable for
      reload (case (1) sequence step §3.2.4 below).

If any pre-condition is not met, abort and resolve the gap before
proceeding. A rotation against a degraded substrate has no roll-
back path that does not also rotate the wakir-orchestrator
network — a strict-no-go for Phase-2.

---

## 3. Rotation-Steps (CA-cadence rotation, case 1)

### 3.1 Bundle generation (SPIRE-Server-side)

```bash
# Generate a new upstream-CA on the SPIRE-Server. Operator-Hand;
# this requires shell access to the SPIRE-Server container.
podman exec wakir-spire-server \
    /opt/spire/bin/spire-server upstreamauthority rotate

# Verify the new bundle is registered.
podman exec wakir-spire-server \
    /opt/spire/bin/spire-server bundle show > /tmp/new-bundle.pem
```

Expected output: a PEM-encoded bundle containing both the
**outgoing** CA (for in-flight SVID validation) and the **incoming**
CA. SPIRE-Server keeps the outgoing CA in the bundle for the
duration of the longest-lived issued SVID's TTL plus a safety
margin (Phase-2 boring-default: 15 minutes JWT-SVID TTL + 5 minute
margin = 20 minutes overlap window).

### 3.2 Distribution

The trust-bundle distribution path depends on the consumer set:

#### 3.2.1 SPIRE-Agent

The agent fetches the trust-bundle from the SPIRE-Server via the
shared Admin-API gRPC socket (`/run/spire/sockets` volume in both
Quadlet and compose layouts). **No manual distribution required**;
the agent's `WatchTrustBundle` stream pushes the update.

Verification:

```bash
podman exec wakir-spire-agent \
    /opt/spire/bin/spire-agent api fetch x509 -socketPath \
    /run/spire/agent-sockets/api.sock
```

Expected: the response includes the new trust-bundle CA-chain.

#### 3.2.2 Persona-containers (Phase-2.3+)

Persona-containers consume the trust-bundle via the SPIFFE-
Workload-API `WatchX509Bundles` stream on the
`wakir-spire-agent-sockets.volume` shared mount. **No manual
distribution required**; the persona-container's Workload-API
client picks up the new bundle on the next stream-push.

Verification (per persona-container, operator-hand):

```bash
podman exec <persona-container> \
    spiffe-helper -socketPath /run/spire/agent-sockets/api.sock \
    -inspect-bundles
```

#### 3.2.3 NATS-Server (Phase-2.4+)

NATS-Server with JWT-Auth enabled reads the trust-bundle from a
file path declared in its config. The bundle file must be
updated **before** NATS-Server is reloaded. Two operator paths:

**Path A — Bundle-file-watch (preferred):** Configure NATS-Server's
trust-bundle path as a SPIFFE-side-car-written file. The
`spiffe-helper` daemon on the NATS host writes the bundle to
`/etc/wakir/nats/trust-bundle.pem` on every `WatchX509Bundles`
push; NATS-Server picks up the new file via its inotify-watch.

**Path B — Manual reload (fallback):**

```bash
# Write the new bundle to the NATS-Server-readable path.
podman cp wakir-spire-server:/tmp/new-bundle.pem \
    /etc/wakir/nats/trust-bundle.pem

# Trigger NATS-Server config reload.
podman exec wakir-nats nats-server --signal reload
```

#### 3.2.4 NATS-Server-Config-Reload semantics

NATS-Server reload is a SIGHUP-equivalent that re-reads the config
file. Existing connections are NOT torn down; in-flight JWTs
continue to validate against the **previous** trust-bundle until
the connection cycles. New CONNECT-frames validate against the
new bundle. The 20-minute overlap window (§3.1) ensures no
existing connection is dropped mid-flight.

P7-conjecture: `nats-server --signal reload` semantics verified
against the NATS-Server reload-documentation 2026-05-12; the
overlap-window calculation comes from SPIRE-upstream's default
CA-rollover policy (P2 — exact upstream constants confirmed when
the Phase-2.3 live-gated test runs).

### 3.3 Validation

After distribution, validate that **every** consumer accepts SVIDs
signed by the **new** CA:

```bash
# (a) SPIRE-Server self-check: issue a test JWT-SVID against the
#     new CA and validate via the bundle.
podman exec wakir-spire-server \
    /opt/spire/bin/spire-server entry create \
    -spiffeID spiffe://example.test/test-rotation-probe \
    -parentID spiffe://example.test/agent/$(hostname) \
    -selector unix:uid:1000 \
    -ttl 60

# (b) SPIRE-Agent fetch + validate.
podman exec wakir-spire-agent \
    /opt/spire/bin/spire-agent api fetch jwt \
    -audience nats://wakir.local \
    -spiffeID spiffe://example.test/test-rotation-probe \
    -socketPath /run/spire/agent-sockets/api.sock

# (c) NATS-Server connection probe (Phase-2.4+ only).
nats --server tls://127.0.0.1:4222 \
    --creds /tmp/test-rotation-probe.jwt \
    server check connection
```

**Acceptance gate:** all three probes return zero exit code and
the JWT-SVID `iss` claim references the **new** trust-bundle's CA
issuer hash. If any probe fails, proceed to §5 (roll-back).

### 3.4 Cutover

The cutover is implicit — once §3.3 validation passes, the new CA
is the default-issuance CA. The previous CA remains in the bundle
for the overlap window, after which the next `spire-server
bundle prune` cycle removes it:

```bash
podman exec wakir-spire-server \
    /opt/spire/bin/spire-server bundle list \
    -format pem | head -5

# Expected: only the new CA's PEM block present after the overlap
# window expires (default Phase-2: 20 minutes after rotation).
```

### 3.5 Cleanup

```bash
# Archive the previous bundle to the timestamp directory.
mv /var/lib/wakir/spire/bundles/current.pem \
    /var/lib/wakir/spire/bundles/$(date -u +%Y-%m-%dT%H%M%SZ)-pre-rotation.pem

# Persist the new bundle as the current pointer.
podman exec wakir-spire-server \
    /opt/spire/bin/spire-server bundle show \
    > /var/lib/wakir/spire/bundles/current.pem

# Record the rotation event in the activity log.
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) trust-bundle-rotation case=ca-cadence \
operator=$USER" >> /var/lib/wakir/spire/rotation-log.txt
```

---

## 4. Rotation-Steps (Trust-Domain migration, case 2)

The Phase-3a trust-domain switch from `example.test` to
`<FTD-ID>.wakir.dev` is **not a rolling rotation**. It is a
substrate-recreate event because:

- Every existing SVID's `sub` claim contains the old trust-domain
  literal and cannot be re-signed under the new domain.
- SPIRE-Server's datastore tags every workload registration with
  the trust-domain; switching requires re-creating the datastore
  or running a SPIRE-upstream-supported migration tool.
- Federation routes (V-908 N2) referencing the old trust-domain
  must be re-registered.

### 4.1 Pre-migration checklist

- [ ] **Aisha-Marker-Recording for the trust-domain switch.**
- [ ] **Reza-Z-A-Ack** for the federation-trust-domain literal
      (V-908 FTD-ID slug format `[a-z][a-z0-9-]{2,30}`).
- [ ] **NATS-Server downtime window** scheduled — connections
      issued under `example.test` will be invalidated.
- [ ] **Tomás Zone-C ack** for any image-pin changes that ship
      with the migration (parity with Sprint-6-Tag-8 workflow).

### 4.2 Migration steps

```bash
# (a) Drain persona-containers gracefully.
sudo systemctl stop wakir-orchestrator-personas.target  # operator-defined

# (b) Stop SPIRE-Agent, then SPIRE-Server (reverse boot order).
sudo systemctl stop wakir-spire-agent.service
sudo systemctl stop wakir-spire-server.service

# (c) Update the config files to the new trust-domain.
sudo $EDITOR /etc/wakir/spire-server.conf  # set trust_domain
sudo $EDITOR /etc/wakir/spire-agent.conf   # set trust_domain (must match)

# (d) Drop the SPIRE-Server data volume (CA + datastore reset).
podman volume rm wakir-spire-server-data
podman volume rm wakir-spire-agent-data

# (e) Restart in boot order.
sudo systemctl start wakir-spire-server.service
sudo systemctl start wakir-spire-agent.service

# (f) Re-create workload-registrations for the new trust-domain.
# (out-of-scope for this runbook; see SPIRE upstream
# entry-creation documentation.)

# (g) Resume persona-containers.
sudo systemctl start wakir-orchestrator-personas.target
```

**Acceptance gate:** all persona-containers report
`spiffe://<FTD-ID>.wakir.dev/...` SPIFFE-IDs in their next
`WatchJWTSVIDs` push. If any container still reports
`example.test`, abort and resolve config drift before resuming.

---

## 5. Failure-modes and roll-back

### 5.1 Bundle generation fails (§3.1)

**Symptom:** `spire-server upstreamauthority rotate` returns
non-zero, or the bundle PEM is empty/malformed.

**Cause-candidates:**
- SPIRE-Server's disk-KeyManager is read-only (rootfs-readonly
  violation; check tmpfs mount integrity).
- Datastore is locked (concurrent rotation in progress).
- Upstream-authority plugin misconfiguration.

**Roll-back:** No state changed yet — abort the rotation, leave
the previous CA in place, file an operator-incident and resolve
the cause-candidate. Re-attempt after fix.

### 5.2 Agent fails to pick up the new bundle (§3.2.1)

**Symptom:** `spire-agent api fetch x509` returns the old bundle
after § 3.2.1 verification.

**Cause-candidates:**
- Agent's `WatchTrustBundle` stream is wedged (agent-server gRPC
  connection lost).
- Shared `wakir-spire-server-sockets.volume` mount is stale.

**Roll-back-path A (preferred):** Restart the SPIRE-Agent service
to re-establish the stream:

```bash
sudo systemctl restart wakir-spire-agent.service
# Wait for healthcheck-green.
podman healthcheck run wakir-spire-agent
# Re-verify §3.2.1.
```

**Roll-back-path B (full revert):** If the agent still fails,
revert the SPIRE-Server to the previous bundle:

```bash
podman cp /var/lib/wakir/spire/bundles/<previous-timestamp>.pem \
    wakir-spire-server:/var/lib/spire/server/restored-bundle.pem
podman exec wakir-spire-server \
    /opt/spire/bin/spire-server bundle set \
    -bundle /var/lib/spire/server/restored-bundle.pem
```

### 5.3 NATS-Server reload fails (§3.2.3 Path B)

**Symptom:** `nats-server --signal reload` returns non-zero, or
new CONNECT-frames are rejected after reload.

**Cause-candidates:**
- Trust-bundle file path is wrong or unreadable.
- Bundle PEM is malformed.
- NATS-Server config file references a different bundle path
  than the operator wrote to.

**Roll-back-path:** Revert the bundle file to the previous PEM and
reload again:

```bash
cp /var/lib/wakir/spire/bundles/<previous-timestamp>.pem \
    /etc/wakir/nats/trust-bundle.pem
podman exec wakir-nats nats-server --signal reload
```

NATS-Server's reload semantics keep existing connections alive —
the roll-back-path does not drop in-flight workload traffic.

### 5.4 Validation probe fails (§3.3)

**Symptom:** One of the §3.3 probes returns non-zero or the JWT-
SVID `iss` claim still references the old CA.

**Cause-candidates:**
- Workload-registry entry is stale (selectors no longer match the
  test-probe workload).
- Agent has cached the previous SVID in `/var/lib/spire/agent`.

**Roll-back-path:** Drop the agent's data volume and restart, then
re-attempt validation:

```bash
sudo systemctl stop wakir-spire-agent.service
podman volume rm wakir-spire-agent-data
sudo systemctl start wakir-spire-agent.service
```

If validation still fails after a clean agent restart, escalate
to a full case-1 roll-back (revert SPIRE-Server bundle per §5.2
Path B).

---

## 6. Operator-Disziplin

- **No live operations from sandbox.** ADR-0051 (rejected; the
  rejection IS the directive) makes the Mira-Sandbox host-podman-
  socket explicitly off-limits. Every command in this runbook is
  Operator-Hand on the host.
- **Tool-Surface-Stempel (ADR-0050) per session.** Operator
  records the tool-surface used (podman, systemctl, cosign,
  skopeo, nats-cli) in the rotation-log.
- **Worktree-Pattern (ADR-0049) für config edits.** Operator
  edits to `/etc/wakir/spire-server.conf` etc. happen in a
  pre-staged worktree on a non-prod host first; production-host
  config changes are atomic copy-in operations only.
- **Pre-Box-Worktree (ADR-0049) Anker.** This runbook authored
  in `/tmp/kai-sprint-6-tag-11-runtime` per the Sprint-6 Tag-10
  tip `7c16f5d` worktree pattern.

---

## 7. Open Items (Phase-2.6 box-end)

- **OI-RB1:** Phase-2.4 NATS-JWT-Auth bring-up is operator-hand;
  the §3.2.3/§3.2.4 steps assume that bring-up has happened. The
  hermetic Phase-2.1/2.2 substrate alone does not require these
  steps.
- **OI-RB2:** Compromise-response timeline (case 3) is deferred
  to a Phase-3-trigger slot. The mechanics in §3 still apply but
  the timeline tightens (target: full rotation within 60 min of
  compromise detection).
- **OI-RB3:** SPIRE-Server's `bundle prune` cadence is upstream-
  defaulted; Wakir-side override is a Phase-3 config-knob slot.
- **OI-RB4:** `spiffe-helper` integration for NATS-Server (§3.2.3
  Path A) is a Phase-2.5+ slot — currently only Path B (manual
  reload) is exercised in the hermetic test suite.
- **OI-RB5:** Live-gated end-to-end test (`WAKIR_SPIRE_LIVE=1`
  AND `WAKIR_NATS_LIVE=1`) for the full rotation sequence is the
  Phase-2.5 box-2 follow-up item.

---

## 8. Verification (P5 + P7 stamps)

- **Authoring-Zeitstempel:** `date -u 2026-05-12T18:47:56Z`.
- **§4.2 cross-reference verified:** `docs/spiffe-z-a-jwt-svid-
  skizze.md` §4.2 (Sequenz-Schritte Phase-2-Boot) is the
  canonical reference; lines 295-340 in the Sprint-6 Tag-10 tip
  `7c16f5d` worktree.
- **Phase-2.6 marker verified:** SPIFFE-Skizze §9 phase-plan
  Phase-2.6 entry "Trust-Bundle-Rotation-Sequence" — this
  runbook is the Phase-2.6 deliverable.
- **Reza-Z-A-Ack-Slot-4 §4.4 verified:** DevOps-track Operations
  ownership of trust-bundle-rotation confirmed in
  `agents-workspaces/reza/outbox/2026-05-11-z-a-cross-review-ack.md`
  §4.4.
- **Hermetic mode invariants:** No live SPIRE-Server in this
  runbook's authoring path. All command shapes verified against
  the SPIRE 1.14.6 CLI reference (P7-conjecture; exact exit-
  code semantics confirmed once Phase-2.3 live-gated test runs).

— Kai
