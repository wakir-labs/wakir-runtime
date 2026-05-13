<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# SELinux-AVC Defense-in-Depth Recipe

Companion document to the Sprint-9-Tag-5 SPIRE-Agent stability fix
(`PILOT_BRING_UP_TROUBLESHOOTING.md` §H2). This document captures the
Operator-Hand recipes for handling SELinux AVC-Denials that COULD
manifest on the Fedora-CoreOS Pilot-VM after the H1 single-org config
substance-fix lands.

**Sandbox boundary:** every step below is **Operator-Hand on the live
VM** (ADR-0051 + `feedback_sandbox_host_trennung.md`). The hermetic
test surface in `tests/infra/test_pilot_bringup_single_org_config.py`
asserts only static template shape; AVC-detection requires `ausearch`
on a real `auditd` log.

## When this document applies

If after the Sprint-9-Tag-5 substance-fix the SPIRE-Server still
crash-loops AND the journal mentions any of:

- `permission denied` on `/var/lib/spire/server/*` or
  `/var/lib/spire/agent/*`
- `failed to open data store: open ...: permission denied`
- `unable to create file ...: permission denied`

then SELinux is the likely cause and this recipe applies.

## Step 1: detect the AVC

On the Pilot-VM:

```
# All AVC-Denials in the last hour.
sudo ausearch -m AVC -ts recent | head -200

# Just the AVC-Denials related to SPIRE.
sudo ausearch -m AVC -ts recent \
  | grep -E 'comm="spire-(server|agent)"|name="(server|agent)\.conf"' \
  | head -40

# Audit-readable summary (semodule-friendly).
sudo ausearch -m AVC -ts recent --raw | audit2why | head -40
```

If `audit2why` reports `Constraint rule:` for `container_t`-process
accessing `var_lib_t` (or `unlabeled_t`) on the spire volume, this is
the volume-relabel-miss path described in
`PILOT_BRING_UP_TROUBLESHOOTING.md` §H2.

## Step 2: fast operator-hand fix (no policy change)

The fastest fix is to relabel the volume mountpoint to
`container_file_t` manually. Podman managed volumes normally get
this label automatically, but a fresh volume created before the
SELinux-policy module that handles `container_file_t` was loaded
may end up `unlabeled_t`.

```
# Find each spire-volume's mountpoint.
for v in $(sudo podman volume ls --format '{{.Name}}' \
            | grep '^wakir-spire-'); do
  mp=$(sudo podman volume inspect "$v" \
        | jq -r '.[0].Mountpoint')
  echo "Relabeling $v at $mp"
  sudo chcon -Rt container_file_t "$mp"
done

# Restart the services.
sudo systemctl restart \
    wakir-spire-server-federation-wakir.service \
    wakir-spire-agent-wakir.service
sleep 30
sudo systemctl status \
    wakir-spire-server-federation-wakir.service \
    wakir-spire-agent-wakir.service
```

## Step 3: persistent fix (custom SELinux policy)

If the `chcon` from Step 2 reverts after a reboot or after a Podman-
volume-prune cycle, generate a persistent custom SELinux policy
module from the AVC log:

```
# Dump the AVCs to a file (audit2allow reads from stdin).
sudo ausearch -m AVC -ts recent --raw > /tmp/spire-avcs.log

# Generate a candidate policy.
sudo audit2allow -M wakir-spire-fix -i /tmp/spire-avcs.log

# Review the generated policy BEFORE installing.
cat wakir-spire-fix.te
```

The generated `wakir-spire-fix.te` typically looks like:

```
module wakir-spire-fix 1.0;

require {
    type container_t;
    type unlabeled_t;
    type var_lib_t;
    class file { read write open getattr };
    class dir { read write search getattr };
}

#============= container_t ==============
allow container_t unlabeled_t:file { read write open getattr };
allow container_t var_lib_t:dir { read write search getattr };
```

**Do not install the auto-generated policy unmodified.** Allowing
`container_t` to read/write `unlabeled_t` opens a broad attack
surface. Prefer the relabel path (Step 2) plus the canonical
`wakir-spire-pilot.te` baseline below.

## Step 4: canonical Wakir-SPIRE-Pilot SELinux baseline

The `wakir-spire-pilot.te` snippet below is the canonical minimal
policy for the Phase-1b Pilot-VM. It does NOT grant any new permissions
— it merely declares the type-transitions that ensure podman-managed
volumes for the SPIRE-Server + SPIRE-Agent always get
`container_file_t` regardless of the host's default file_contexts.

```
module wakir-spire-pilot 1.0;

require {
    type container_file_t;
    type container_var_lib_t;
    type container_runtime_t;
}

# Declare the type-transition so a freshly created file under
# /var/lib/containers/storage/volumes/wakir-spire-*/_data inherits
# container_file_t regardless of the host policy.
type_transition container_runtime_t container_var_lib_t : file container_file_t;
type_transition container_runtime_t container_var_lib_t : dir container_file_t;
```

Install (Operator-Hand on the Pilot-VM):

```
cd /opt/wakir-runtime/infra/spire/federation/selinux
sudo checkmodule -M -m -o wakir-spire-pilot.mod wakir-spire-pilot.te
sudo semodule_package -o wakir-spire-pilot.pp -m wakir-spire-pilot.mod
sudo semodule -i wakir-spire-pilot.pp

# Verify the module is loaded.
sudo semodule -l | grep wakir-spire-pilot

# Re-relabel the volumes one final time (the new transition only
# applies to NEW files; existing files keep their old label).
sudo restorecon -Rv /var/lib/containers/storage/volumes/wakir-spire-*/
```

## Step 5: verify the fix

After Step 2 (relabel) or Step 4 (policy), the smoke-test should
return to 6/6 PASS:

```
sudo /opt/wakir-runtime/bin/proxmox-bringup-smoke --org acme
```

If the smoke is still partial, the AVC was not the root cause — fall
back to `PILOT_BRING_UP_TROUBLESHOOTING.md` §H4 (config-path
mismatch) or §H5 (trust-domain literal mismatch).

## Notes on Podman + SELinux on Fedora-CoreOS

- Fedora-CoreOS ships SELinux in **enforcing** mode by default. The
  Wakir-Pilot-VM does NOT switch to permissive — keep enforcing for
  the substrate-hardening posture (ADR-0020 §V-908).
- Podman handles named-volume relabeling automatically via the
  `container-selinux` policy package, which is part of the base
  CoreOS install. If `rpm -q container-selinux` returns
  ``package container-selinux is not installed`` you have a
  misconfigured CoreOS — file an issue against the Ignition that
  built the VM image.
- For bind-mounts of host-side config files (e.g. the
  `/etc/wakir/spire-federation/spire-server-<SIDE>.conf` mount in
  the SPIRE-Server-Federation Quadlet template), the `:ro,Z` flag in
  the `Volume=` directive forces a PRIVATE relabel — exactly what we
  want for a single-container config file. The `:z` (shared) variant
  would also work but is wider than necessary.

## References

- Podman SELinux relabel flags (`:z` / `:Z`):
  https://docs.podman.io/en/v4.3/markdown/options/volume.html
- container_file_t / container_t SELinux types:
  https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/8/html/using_selinux/creating-selinux-policies-for-containers_using-selinux
- `audit2allow` policy synthesis:
  https://access.redhat.com/solutions/3268521 (gated; mirror in
  upstream `policycoreutils-python-utils` manpage)

— Kai
