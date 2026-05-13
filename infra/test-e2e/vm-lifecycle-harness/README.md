<!--
SPDX-License-Identifier: BUSL-1.1
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# Disposable-VM E2E Acceptance-Gate Harness — Sprint-9 Tag-5

Operator-hand-run substrate that materialises a single-use Fedora-CoreOS
VM, drives the full `wakir-pilot-bootstrap.sh` end-to-end against the
real (un-stubbed) systemd + podman + curl surface, and grades the result
through `proxmox-bringup-smoke`. The acceptance gate is binary: **6/6
PASS or the gate fails**.

This closes the sandbox-hermetic-test gap documented in the Mira-Memory
`feedback_live_bringup_sandbox_gap.md` (2026-05-13): seven substance
bugs slipped past the hermetic sandbox tests of Sprint-9 Tag-4 and
surfaced only during the Operator-Hand bring-up of 2026-05-13 ~12:45
CEST.

## Why a real VM and not the Sprint-9 Tag-4 Fedora-container substrate

The Tag-4 container suite (`tests/infra/test_pilot_bringup_e2e_container.py`)
stubs `systemctl`, `podman`, `curl`, `git`, `proxmox-bringup-smoke`. The
stubs let CI exercise the bootstrap *control flow*, but they never
materialise:

- a Quadlet generator over real `.container`/`.volume` files,
- a real SPIRE-Server/Agent process pair,
- a real NATS-JetStream node serving `/jsz`,
- a real Bucket-Init Python container resolving its imports,
- a real systemd unit-dependency graph.

Any of the seven 2026-05-13 substance bugs (Volume-filename mismatch,
Agent-Requires mismatch, Python `cryptography` ModuleNotFoundError,
SPIRE-Server restart loop, etc.) lives in exactly that layer.

The Tag-5 harness fixes the gap by running the bootstrap inside a
genuine Fedora-CoreOS QEMU VM with a fresh Ignition config on every
invocation. The VM is disposable: cold-start, drive, grade, destroy.

## Provider topology

The harness is provider-agnostic at the seam `vm-up.sh` / `vm-down.sh`,
with two implementations shipped:

1. **`qemu` (default)** — `qemu-system-x86_64` with a downloaded Fedora-
   CoreOS qcow2 image and an Ignition config rendered from
   `ignition.bu.tmpl`. Self-contained, no Proxmox dependency, suitable
   for any Linux host with `qemu-kvm` + `butane` + `xz` available.
2. **`proxmox` (opt-in)** — issues `qm clone` from the Pilot-VM template
   (Operator-Hand-provisioned per `PROXMOX_BRING_UP_RECIPE.md` §1) and
   destroys the clone at teardown. Selected via `WAKIR_E2E_VM_PROVIDER=
   proxmox`. Intended for the canonical Phase-1b Pilot environment.

Both providers must satisfy the same contract: at the end of `vm-up.sh`
the harness must be able to `ssh -i $SSH_KEY core@$VM_IP` and execute
arbitrary commands.

## End-to-end flow

```
                         vm-up.sh
                            |
              +-------------v--------------+
              | provider == qemu           |
              |  - download CoreOS qcow2   |
              |  - butane ignition.bu      |
              |  - qemu-system-x86_64 ...  |
              | provider == proxmox        |
              |  - qm clone <tpl> <vmid>   |
              |  - qm start                |
              +-------------+--------------+
                            |
                  wait for ssh:22 ready
                            |
                            v
                  vm-bringup-run.sh
                     (over ssh)
                            |
              +-------------v--------------+
              | scp the repo               |
              | sudo bash wakir-pilot-     |
              |   bootstrap.sh             |
              | sudo bin/proxmox-bringup-  |
              |   smoke --org $ORG --json  |
              +-------------+--------------+
                            |
                            v
                  acceptance-gate.sh
                            |
              +-------------v--------------+
              | parse smoke --json         |
              | exit 0 iff pass == 6/6     |
              | else exit 2 with bug-      |
              |  vector classification     |
              +-------------+--------------+
                            |
                            v
                       vm-down.sh
                  (always runs, trap EXIT)
```

## Bug-vector coverage

`acceptance-gate.sh` does not just check `pass == 6` — it inspects
which checks failed and emits a structured classification that maps
each smoke check to the corresponding 2026-05-13 bug:

| Smoke check                       | Failure implies                              |
|-----------------------------------|----------------------------------------------|
| `quadlet-units-active`            | Bug 2 (Volume-filename) or Bug 5 (idempotency) |
| `nats-jetstream-reachable`        | Bug 6 (Bucket-Init cryptography ModuleNotFound) cascade |
| `spire-server-healthy`            | Bug 7 (Server restart loop)                  |
| `spire-agent-healthy`             | Bug 3, Bug 4 (Agent Volume-/Service-name)    |
| `spire-workload-api-reachable`    | Bug 3, Bug 4, Bug 7 cascade                  |
| `marker-stack-bucket-present`     | Bug 6 (Bucket-Init crash)                    |

Plus a non-smoke pre-flight assertion against Bug 1 (resume-hint
`bash bash` doubling) by inspecting `bootstrap-run.log`.

This is the structured regression-net the bug bilanz called for.

## Sandbox-Disziplin (ADR-0051)

This harness is **operator-hand-run substrate**. It does not run inside
the claude-dev sandbox. Three reasons:

1. ADR-0051 forbids host-podman / host-libvirt socket access from the
   sandbox.
2. QEMU + KVM requires `/dev/kvm` access and a real (non-nested)
   hypervisor surface.
3. Smoke-test results from a sandbox-internal VM are not evidence of
   the real Fedora-CoreOS path the Pilot-VM uses.

The hermetic tests under `tests/infra/test_vm_e2e_acceptance_gate.py`
exercise the harness *logic* (state transitions, gate grading, bug-
vector classification) with mock VM substrate fixtures. Those run in
the sandbox and in CI. The real VM run is Operator-Hand.

## Usage (Operator-Hand)

```bash
# Default: qemu provider, ephemeral VM, ORG=acme, branch=main
sudo /opt/wakir-runtime/infra/test-e2e/vm-lifecycle-harness/vm-up.sh
sudo /opt/wakir-runtime/infra/test-e2e/vm-lifecycle-harness/vm-bringup-run.sh
/opt/wakir-runtime/infra/test-e2e/vm-lifecycle-harness/acceptance-gate.sh
sudo /opt/wakir-runtime/infra/test-e2e/vm-lifecycle-harness/vm-down.sh
```

Or in one shot (trap-EXIT teardown):

```bash
sudo /opt/wakir-runtime/infra/test-e2e/vm-lifecycle-harness/run-acceptance-gate.sh \
  --org acme \
  --branch main \
  --provider qemu
```

## CI integration

The CI lane `e2e-vm-acceptance-gate` (in
`.github/workflows/e2e-vm-acceptance-gate.yml`) does NOT trigger a
real VM run in GitHub Actions — that requires nested-virt that the
default `ubuntu-latest` runner does not reliably provide. Instead the
lane runs the **hermetic harness-logic tests** that prove the gate
script grades correctly given a mock smoke JSON.

The real-VM lane is triggered manually by the Operator-Hand on a host
with `/dev/kvm`. Outputs (logs, smoke JSON, gate verdict) are uploaded
back to the PR as evidence.

Future work (post-Phase-1b): self-hosted GitHub-Actions runner with
nested-KVM on the Proxmox host so the real-VM lane can run automatically
on each PR touching the bootstrap script. Tracked under
`needs-attention.md`.

## Operator-Hand-Run Note

The harness is **ready to run** as of merge. The first authoritative
run is gated on:

- Kai-Bug-7 SPIRE-Agent diagnose + fix (Bug 3, 4, 7) merged,
- Tomás-Image-Pin-Idempotency provisioner merged (stable Bucket-Init),
- Reza-NATS-Discrepancy + Wirelang-Import-Disentanglement merged (Bug 6),
- Pilot-VM rolled back to `pre-bring-up` snapshot.

Bring-up-2 from the Mira-Bug-Bilanz §"Pilot-Phase-Verschiebung" is the
first run scheduled.

— Amara
