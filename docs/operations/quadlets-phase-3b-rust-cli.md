<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Operator-Recipe — Phase-3b Rust-CLI Binary Installer Quadlets

**Tag-22 Mini-Welle** · Operations-Reife · Single-PR-Bundle
**Status:** Operator-Hand live bring-up after Cross-Review Zone-C
digest resolution. Hermetic format-validation tests live in
`tests/infra/test_quadlets_phase_3b.py`. (Retry after Tag-21
quota-hit; identical bytes-shape as the aborted Tag-21 draft.)

## 1. Scope

The Phase-3b Rust-default switches (Tag-17/18/19/20 Mini-Welle PRs
[#167](https://github.com/wakir-labs/wakir-runtime/pull/167),
[#169](https://github.com/wakir-labs/wakir-runtime/pull/169),
[#171](https://github.com/wakir-labs/wakir-runtime/pull/171),
[#175](https://github.com/wakir-labs/wakir-runtime/pull/175))
wire `wirelang.persona_engine.rust_backend_switch` to subprocess-bridge
to five Rust-CLI binaries at the canonical `/opt/wakir/bin/` paths:

| # | Binary | Crate | Switch | Landed |
|---|---|---|---|---|
| 1 | `wakir-persona-engine-recovery` | `wirelang-rust/crates/persona-engine-recovery` | `WAKIR_RECOVERY_BACKEND=rust` | PR #167 (Tag-17) |
| 2 | `wakir-persona-engine-state-backing` | `wirelang-rust/crates/persona-engine-state-backing` | `WAKIR_STATE_BACKING_BACKEND=rust_{inmemory,natskv}` | PR #167 (Tag-17) |
| 3 | `wakir-persona-engine-fsm` | `wirelang-rust/crates/persona-engine-fsm` | `WAKIR_FSM_BACKEND=rust` | PR #169 (Tag-18) |
| 4 | `wakir-persona-engine-v907-verify` | `wirelang-rust/crates/persona-engine-v907-verify` | `WAKIR_V907_VERIFY_BACKEND=rust` | PR #171 (Tag-19) |
| 5 | `wakir-persona-engine-bridge-diff` | `wirelang-rust/crates/persona-engine-bridge-diff` | `WAKIR_BRIDGE_DIFF_BACKEND=rust` | PR #175 (Tag-20) |

The Tag-22 Quadlet bundle delivers two unit files:

- `quadlet/wakir-rust-cli.container` — oneshot installer
- `quadlet/wakir-rust-cli-bin.volume` — host-side binary named-volume

The installer runs once at boot, copies the five binaries from the
carrier image `ghcr.io/wakir-labs/wakir-persona-engine` into the
host-side `/opt/wakir/bin/` directory, then exits. All five binaries
ship inside the carrier image (the same digest-pinned image the
`wakir-persona-tomas.container` Quadlet runs); this unit exposes
them to out-of-container consumers without duplicating the build
substrate.

## 2. Cross-Review Anchors

- **Zone C (Container-Image-Pipeline x Tomás-OTS-Anchoring):** the
  carrier image is the same `wakir-persona-engine` image that the
  Tag-15-Konsens-Bundle persona-tomas Quadlet pins. No new image-
  build path is introduced; the Quadlet consumes the existing
  carrier image. The image-digest placeholder
  `DIGEST_PENDING_KAI_CROSS_REVIEW` is resolved Operator-Hand via
  the same `resolve-image-pins-ci.yml` workflow that resolves the
  Cosign-Policy and the persona-tomas Quadlet (single-source-of-
  truth digest pin across all three files).

- **Bridge-diff Cosign-Policy gap (Tag-23+ follow-up):**
  `policies/cosign-policy-phase-3b.yaml` currently inventories the
  four Tag-17/18/19 binaries (recovery, state-backing, fsm,
  v907-verify). The bridge-diff binary (Tag-20 PR #175) is wired
  into `rust_backend_switch.py` and shipped in the carrier image
  but is not yet listed in the Cosign-Policy inventory. The
  Quadlet installer above explicitly installs all five binaries;
  the Cosign-Policy 5-binary-inventory extension is tracked as a
  Tag-23+ follow-up in the Tag-22 lieferbericht. The carrier-image
  digest pin already covers bridge-diff transitively (the binary
  is signed via the same Sigstore-keyless OIDC identity as the
  carrier image itself).

## 3. Operator install path (rootful Podman, FCOS Pilot-VM)

```bash
# 0. Pre-resolve the carrier-image digest via Cross-Review Zone-C.
#    The resolve-image-pins-ci.yml workflow propagates the digest
#    into all three substrates simultaneously (Cosign-Policy,
#    persona-tomas Quadlet, this Quadlet). Without the resolved
#    digest the unit refuses to start (Podman rejects the
#    DIGEST_PENDING placeholder).

# 1. Install the Quadlet unit + named-volume.
sudo install -m 644 quadlet/wakir-rust-cli.container \
    /etc/containers/systemd/wakir-rust-cli.container
sudo install -m 644 quadlet/wakir-rust-cli-bin.volume \
    /etc/containers/systemd/wakir-rust-cli-bin.volume

# 2. Pre-create the host-side install location with the right
#    SELinux context. The :Z relabel in the Quadlet's Volume=
#    directive handles the per-volume label; the parent /opt/wakir
#    directory is operator-staged.
sudo install -d -m 755 /opt/wakir/bin

# 3. Trigger the Quadlet generator + start the unit.
sudo systemctl daemon-reload
sudo systemctl start wakir-rust-cli.service
```

## 4. Verification (Operator-Hand per ADR-0051)

```bash
# Unit succeeded? (RemainAfterExit=yes -> "active (exited)" is OK)
systemctl status wakir-rust-cli.service

# Installer logged a final "OK" line?
journalctl -u wakir-rust-cli.service --since '5 min ago' \
    | grep '^OK$'

# All five binaries in place + executable?
ls -l /opt/wakir/bin/wakir-persona-engine-*
for b in recovery state-backing fsm v907-verify bridge-diff; do
    test -x "/opt/wakir/bin/wakir-persona-engine-$b" \
        || { echo "MISSING: $b" >&2; exit 2; }
done; echo OK

# Each binary self-reports version?
/opt/wakir/bin/wakir-persona-engine-recovery --version
/opt/wakir/bin/wakir-persona-engine-state-backing --version
/opt/wakir/bin/wakir-persona-engine-fsm --version
/opt/wakir/bin/wakir-persona-engine-v907-verify --version
/opt/wakir/bin/wakir-persona-engine-bridge-diff --version
```

## 5. Re-install / upgrade

The installer is idempotent on the bytes-level — re-running the
unit overwrites the five binary files in `/opt/wakir/bin/` from
the carrier image. To pick up a new carrier-image digest:

```bash
# 1. Pull the new image (Operator-Hand, digest known from
#    resolve-image-pins-ci output).
sudo podman pull \
    ghcr.io/wakir-labs/wakir-persona-engine:0.5.0-pilot@sha256:<new-digest>

# 2. Update the digest in /etc/containers/systemd/wakir-rust-cli.container.
sudo sed -i \
    "s|sha256:DIGEST_PENDING_KAI_CROSS_REVIEW|sha256:<new-digest>|" \
    /etc/containers/systemd/wakir-rust-cli.container

# 3. Restart the unit -> overwrites /opt/wakir/bin/wakir-persona-engine-*.
sudo systemctl daemon-reload
sudo systemctl restart wakir-rust-cli.service
```

## 6. Tear-down

```bash
sudo systemctl stop wakir-rust-cli.service
sudo rm /etc/containers/systemd/wakir-rust-cli.container \
        /etc/containers/systemd/wakir-rust-cli-bin.volume
sudo systemctl daemon-reload

# Purge the host-side binary copies (carrier image untouched).
sudo rm /opt/wakir/bin/wakir-persona-engine-*
podman volume rm wakir-rust-cli-bin
```

## 7. On-failure posture

| Failure mode | Operator action |
|---|---|
| Unit fails with `image refused: invalid digest` | Resolve the placeholder via `resolve-image-pins-ci.yml` (Zone-C). Re-run the unit after `sed`-replacing the digest. |
| Installer exits 2 with `missing or non-exec` | Carrier-image drift — the digest you have does NOT ship all five binaries. Halt rollout, escalate to Zone-C cross-review (was the image rebuilt without the Tag-20 bridge-diff binary?). |
| `/opt/wakir/bin/<binary> --version` segfaults on the host | Host glibc vs musl mismatch — the binaries are statically linked against musl per the persona-engine Containerfile.real; if this surfaces it indicates a build-substrate drift, not a Quadlet drift. Escalate to Selin / Rust-build-owner. |
| `systemctl status` reports `failed`, `journalctl` shows SELinux denial | The `:Z` relabel-private flag did not run (rare on FCOS but possible on incompletely-relabeled hosts). Run `restorecon -Rv /opt/wakir` and restart. |

## 8. Cross-substrate parity matrix

| Substrate | File | What it pins | Digest-source |
|---|---|---|---|
| Cosign-Policy | `policies/cosign-policy-phase-3b.yaml` | Carrier image + 4 binaries inventory | Operator-Hand resolve-image-pins-ci |
| Persona-tomas Quadlet | `quadlet/wakir-persona-tomas.container` | Carrier image (consumed in-container) | Operator-Hand resolve-image-pins-ci |
| **Rust-CLI installer Quadlet (Tag-22)** | `quadlet/wakir-rust-cli.container` | Carrier image (host-side install) | Operator-Hand resolve-image-pins-ci |

All three substrates carry the same `DIGEST_PENDING_KAI_CROSS_REVIEW`
placeholder slot in the same byte-position, so a single
`resolve-image-pins-ci` run propagates the resolved digest into all
three files in lock-step.

## 9. Sandbox boundary

The hermetic test surface (`tests/infra/test_quadlets_phase_3b.py`)
validates the SHAPE of the Quadlet text — section headers, the five
binaries listed, SELinux flags present, sha256 placeholder slot
canonical-form. No sandbox process calls `podman` or `systemctl`
against the host per `feedback_sandbox_host_trennung.md`. Live
bring-up is Operator-Hand per ADR-0051 Mira-Sandbox-vs-Host-
Operations-Trennung.

— Kai
