<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Pilot-Bring-up Troubleshooting

Companion document to `wakir-pilot-bootstrap.sh` and
`PROXMOX_BRING_UP_RECIPE.md`. Captures the diagnose-recipes for the
Sprint-9-Tag-4 live-bring-up bug bundle (Bug 7: SPIRE-Server / SPIRE-
Agent restart-loop on a single-org Phase-1b pilot VM).

Sandbox boundary: every step below is **Operator-Hand on the live VM**.
The hermetic Sprint-9-Tag-4 test surface (`tests/infra/test_pilot_
bootstrap.py`) does not exercise the live failure modes documented
here — those require an actual SPIRE container runtime.

## Bug 7: SPIRE-Server / SPIRE-Agent restart-loop

### Symptom

After `wakir-pilot-bootstrap.sh` Phase 6 completes (with the Sprint-9-
Tag-4 Bug 1-5 fixes applied), the smoke-test reports:

```
wakir-spire-server-federation-wakir.service: activating (auto-restart) since 4s ago
wakir-spire-agent-wakir.service: inactive (dead)
```

Only the NATS container is healthy; SPIRE-Server crash-loops and the
SPIRE-Agent (with a `Requires=` on the server) refuses to come up at
all.

### Diagnose-recipe (Operator-Hand on the VM)

Run on the pilot VM:

```
# 1. Server container journal -- the immediate crash signal.
sudo journalctl -u wakir-spire-server-federation-wakir.service -n 100 --no-pager

# 2. Container log via podman directly (in case systemd truncated).
sudo podman logs wakir-spire-server-federation-wakir 2>&1 | tail -100

# 3. Configuration shape check.
sudo cat /etc/wakir/spire-federation/spire-server-wakir.conf

# 4. Volume / config bind-mount inspection.
sudo podman inspect wakir-spire-server-federation-wakir \
    | jq '.[0].Mounts, .[0].Config.Env, .[0].State'

# 5. Quadlet generator output (rendered systemd unit).
sudo /usr/libexec/podman/quadlet -dryrun -user 2>&1 | head -200

# 6. SELinux denials (if AVC denials are suspected on Fedora-CoreOS).
sudo ausearch -m AVC -ts recent | tail -40
```

### Hypotheses (ranked by likelihood)

#### H1. Single-org pilot uses federation-config that requires a partner peer

**Probability: very high**

The Sprint-8 Tag-1 `infra/spire/federation/config/spire-server-wakir.
conf` declares a `federates_with "partner.test"` block that points at
`spire-server-partner:8443` inside the `wakir-federation` network. On
a single-org Phase-1b pilot only the `wakir` side is installed — the
`partner` side does not exist, so the SPIRE-Server fails to resolve
the peer DNS name and crashes on bundle-endpoint-fetch.

Mirror failure mode on the agent: `spire-agent-wakir.conf` sets
`insecure_bootstrap = false` and `trust_bundle_path = /var/lib/spire/
bundles/bootstrap.jwks`. With no peer side present, that bootstrap
JWKS is never staged, the agent fails to attest, and stays `inactive
(dead)`.

**Fix-hypothesis (Operator-Hand verify on the VM):**

1. Edit `/etc/wakir/spire-federation/spire-server-wakir.conf` and
   comment out the entire `federates_with "partner.test"` block
   (lines starting at `federates_with` to the closing brace).
2. Edit the same file's `federation { bundle_endpoint { ... } }`
   block. Either delete it (single-org pilot does not export a
   bundle endpoint) or keep it; either form is valid in the
   single-side configuration.
3. Edit `/etc/wakir/spire-agent-wakir.conf`: set `insecure_bootstrap
   = true` and remove the `trust_bundle_path = ...` directive (or
   point it at the local server's bundle export instead of the
   peer-bootstrap JWKS).
4. Re-run:
   ```
   sudo systemctl restart wakir-spire-server-federation-wakir.service
   sleep 30  # CA-init + bundle-endpoint warm-up
   sudo systemctl status wakir-spire-server-federation-wakir.service
   sudo systemctl restart wakir-spire-agent-wakir.service
   sudo systemctl status wakir-spire-agent-wakir.service
   ```

If the server comes up `active (running)` and the agent comes up
`active (running)`, H1 is confirmed and the proper Source-fix is to
ship a **single-org pilot config variant** that omits the
`federates_with` block. Tracked as the follow-up Sprint-9-Tag-5
Source-task (Reza for config-shape spec, Kai for bootstrap template
selection).

#### H2. Volume-permission / SELinux issue on Fedora-CoreOS

**Probability: medium**

The SPIRE-Server container runs as `User=1000:1000` and writes to
`/var/lib/spire/server` (mounted from the
`wakir-spire-server-federation-wakir-data` volume). Fedora-CoreOS uses
SELinux in enforcing mode; podman named-volumes typically carry the
`container_file_t` type, but a fresh volume created before the
bind-mount label-relabel may be `unlabeled_t`.

**Fix-hypothesis:**

```
# Reset volume labels.
sudo podman volume inspect wakir-spire-server-federation-wakir-data \
    | jq -r '.[0].Mountpoint'
# e.g. /var/lib/containers/storage/volumes/wakir-spire-server-.../
sudo chcon -Rt container_file_t <mountpoint>
sudo systemctl restart wakir-spire-server-federation-wakir.service
```

If `journalctl -u ...` mentions `permission denied` on
`/var/lib/spire/server/...`, H2 is the cause. Long-term fix: add
`:z` or `:Z` to the named-volume Volume= directives in the Quadlet
template.

#### H3. CA-init takes longer than HealthStartPeriod=30s

**Probability: low**

The Quadlet template sets `HealthStartPeriod=30s`. On a slow Pilot-VM
the SPIRE-Server's initial CA-key generation + datastore migration
may exceed that window, podman marks the container unhealthy, and
the unit's `Restart=on-failure` triggers a restart loop.

**Fix-hypothesis:**

Bump `HealthStartPeriod=60s` in `quadlet/wakir-spire-server-
federation.container`. Operator-Hand confirm: time the standalone
container with `podman run --rm ... spire-server healthcheck` and
measure the first-success latency.

#### H4. Config-path mismatch (Volume= source vs. spire-server.conf path)

**Probability: low (verified by Phase-6 install logic)**

The Quadlet template binds `/etc/wakir/spire-federation/spire-server-
<SIDE>.conf` read-only at `/etc/spire/server/server.conf` inside the
container. The `Exec=run -config /etc/spire/server/server.conf`
matches. Bootstrap Phase 6c installs the source file at the right
host path. Verify with step 4 of the diagnose-recipe (podman
inspect).

#### H5. Trust-domain literal mismatch between server.conf and agent.conf

**Probability: very low**

Both files declare `trust_domain = "wakir.test"` -- mismatch would
manifest as an attestation-rejection in the agent journal, not a
server crash-loop. Cross-check with `grep trust_domain
/etc/wakir/spire-federation/spire-server-wakir.conf
/etc/wakir/spire-agent-wakir.conf`.

## Operator-Hand-Verify-Recipe (second bring-up attempt)

After the Sprint-9-Tag-4 PR merges and the operator wants to retry
the bring-up:

### Option A: from-scratch (preferred — clean state)

1. On the Proxmox host: `qm rollback <vmid> pre-bring-up`. The
   pre-bring-up snapshot was taken before the first attempt (per
   `wakir-pilot-bootstrap.sh` fail_step hint).
2. SSH into the VM after rollback.
3. `git -C /opt/wakir-runtime pull` (if the repo was cloned before
   the snapshot) or re-run `curl ... | sudo bash` to fetch the
   latest bootstrap.
4. `sudo /opt/wakir-runtime/infra/spire/federation/wakir-pilot-
    bootstrap.sh` (or pipe-from-curl, same as before).
5. The Sprint-9-Tag-4 Bug 1-5 fixes will produce a clean Phase 6
   install with the correct volume / service names.
6. Bug 7 follow-up: if the smoke-test still reports SPIRE-Server
   restart-loop, apply the H1 single-org fix-hypothesis above
   (comment out `federates_with`) and re-run `--resume-from 6`.

### Option B: in-place resume (no snapshot available)

1. On the VM: clear the bad Phase-6 state.
   ```
   sudo systemctl stop wakir-spire-server-federation-wakir.service \
                      wakir-spire-agent-wakir.service \
                      wakir-nats.service 2>/dev/null
   sudo rm -f /etc/containers/systemd/wakir-spire-*.container \
              /etc/containers/systemd/wakir-spire-*.volume \
              /etc/containers/systemd/wakir-federation.network
   sudo systemctl daemon-reload
   ```
2. `git -C /opt/wakir-runtime pull`.
3. `sudo /opt/wakir-runtime/infra/spire/federation/wakir-pilot-
    bootstrap.sh --resume-from 6`.

The Sprint-9-Tag-4 idempotent Phase-6 logic will only write files
where the rendered content differs from the on-disk target.

## Hand-off

For the third bring-up attempt (post-Bug-7-config-fix), the expected
smoke-test outcome is **6/6 PASS** (NATS + SPIRE-Server-healthy +
SPIRE-Agent-healthy + Workload-API-reachable + marker-stack-bucket-
present + bucket-init-oneshot-completed). Any other outcome warrants
a fresh diagnose-recipe pass against the journal output.

— Kai
