<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Operator-Recipe — Phase-3b Rust-CLI Binary Installer Quadlets

**Tag-22 Mini-Welle (+ Tag-24 7-binary, Tag-29 8-binary, Tag-31
9-binary, Tag-45 11-binary extensions)** · Operations-Reife ·
Single-PR-Bundle
**Status:** Operator-Hand live bring-up after Cross-Review Zone-C
digest resolution. Hermetic format-validation tests live in
`tests/infra/test_quadlets_phase_3b.py`. (Retry after Tag-21
quota-hit; identical bytes-shape as the aborted Tag-21 draft. The
Tag-24 Mini-Welle extends the inventory from 5 to 7 binaries in
lock-step with the Cosign-Policy update per ADR-0065 Phase-3c
Trigger-Gate 2+3; Tag-29 7->8 adds svid-workload-identity; Tag-31
8->9 adds bridge-audit-writer; Tag-45 9->11 adds bridge-audit-replay
and migrate-version — closing Reza's Phase-3a-Foundation 15-module
sweep at 15/15 on the Cosign-Policy side and 11/11 on this
carrier-image installer.)

> **Tag-45 cross-reference.** The Tag-45 Operator-Hand recipe
> (Installer-Sequence + Cosign-Verification + Rollback-Pfad pro
> Binary + Cross-Welle-Coordination) lives in
> `docs/phase-3c/quadlet-cosign-15-binary-installer.md`. This
> document remains the canonical Tag-22/24 living operator
> reference; the Tag-45 doc is the substrate-refresh recipe for
> the carrier-image 9->11 + Cosign-Policy 13->15 transition.

## 1. Scope

The Phase-3b Rust-default switches (Tag-17/18/19/20/22/23 Mini-Welle
PRs [#167](https://github.com/wakir-labs/wakir-runtime/pull/167),
[#169](https://github.com/wakir-labs/wakir-runtime/pull/169),
[#171](https://github.com/wakir-labs/wakir-runtime/pull/171),
[#175](https://github.com/wakir-labs/wakir-runtime/pull/175),
[#181](https://github.com/wakir-labs/wakir-runtime/pull/181),
[#184](https://github.com/wakir-labs/wakir-runtime/pull/184))
wire `wirelang.persona_engine.rust_backend_switch` to subprocess-
bridge to seven Rust-CLI binaries at the canonical `/opt/wakir/bin/`
paths:

| # | Binary | Crate | Switch | Landed |
|---|---|---|---|---|
| 1 | `wakir-persona-engine-recovery` | `wirelang-rust/crates/persona-engine-recovery` | `WAKIR_RECOVERY_BACKEND=rust` | PR #167 (Tag-17) |
| 2 | `wakir-persona-engine-state-backing` | `wirelang-rust/crates/persona-engine-state-backing` | `WAKIR_STATE_BACKING_BACKEND=rust_{inmemory,natskv}` | PR #167 (Tag-17) |
| 3 | `wakir-persona-engine-fsm` | `wirelang-rust/crates/persona-engine-fsm` | `WAKIR_FSM_BACKEND=rust` | PR #169 (Tag-18) |
| 4 | `wakir-persona-engine-v907-verify` | `wirelang-rust/crates/persona-engine-v907-verify` | `WAKIR_V907_VERIFY_BACKEND=rust` | PR #171 (Tag-19) |
| 5 | `wakir-persona-engine-bridge-diff` | `wirelang-rust/crates/persona-engine-bridge-diff` | `WAKIR_BRIDGE_DIFF_BACKEND=rust` | PR #175 (Tag-20) |
| 6 | `wakir-persona-engine-subscribe-loop` | `wirelang-rust/crates/persona-engine-subscribe-loop` | `WAKIR_SUBSCRIBE_LOOP_BACKEND=rust` | PR #181 (Tag-22) |
| 7 | `wakir-persona-engine-anchor-emitter` | `wirelang-rust/crates/persona-engine-anchor-emitter` | `WAKIR_ANCHOR_EMITTER_BACKEND=rust` | PR #184 (Tag-23) |
| 8 | `wakir-persona-engine-svid-workload-identity` | `wirelang-rust/crates/persona-engine-svid-workload-identity` | `WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND=rust` | PR #191 + Tag-29 |
| 9 | `wakir-persona-engine-bridge-audit-writer` | `wirelang-rust/crates/persona-engine-bridge-audit-replay` | `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust` | Tag-31 |
| 10 | `wakir-persona-engine-bridge-audit-replay` | `wirelang-rust/crates/persona-engine-bridge-audit-replay` | `WAKIR_BRIDGE_AUDIT_REPLAY_BACKEND=rust` | PR #246 (Tag-37 / Tag-45) |
| 11 | `wakir-persona-engine-migrate-version` | `wirelang-rust/crates/persona-engine-migrate-version` | `WAKIR_MIGRATE_VERSION_BACKEND=rust` | PR #250 (Tag-38 / Tag-45) |

The Tag-22/24 Quadlet bundle delivers two unit files:

- `quadlet/wakir-rust-cli.container` — oneshot installer
- `quadlet/wakir-rust-cli-bin.volume` — host-side binary named-volume

The installer runs once at boot, copies the seven binaries from the
carrier image `ghcr.io/wakir-labs/wakir-persona-engine` into the
host-side `/opt/wakir/bin/` directory, then exits. All seven
binaries ship inside the carrier image (the same digest-pinned
image the `wakir-persona-tomas.container` Quadlet runs); this unit
exposes them to out-of-container consumers without duplicating the
build substrate.

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

- **Cosign-Policy parity (Tag-23 + Tag-24 closed):**
  `policies/cosign-policy-phase-3b.yaml` now inventories the same
  seven binaries this Quadlet installer iterates. Tag-23 Mini-Welle
  PR #182 closed the `bridge-diff` gap (5-binary inventory); the
  Tag-24 Mini-Welle (this PR) extends both substrates in lock-step
  to a 7-binary inventory, adding `subscribe-loop` (Tag-22 PR #181)
  and `anchor-emitter` (Tag-23 PR #184). The
  cross-substrate parity test
  (`test_cross_substrate_parity_with_quadlet_installer`) enforces
  the agreement at policy-author time. The carrier-image digest pin
  covers all seven binaries transitively (same Sigstore-keyless OIDC
  identity for the entire carrier image).

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

# All seven binaries in place + executable?
ls -l /opt/wakir/bin/wakir-persona-engine-*
for b in recovery state-backing fsm v907-verify bridge-diff subscribe-loop anchor-emitter; do
    test -x "/opt/wakir/bin/wakir-persona-engine-$b" \
        || { echo "MISSING: $b" >&2; exit 2; }
done; echo OK

# Each binary self-reports version?
/opt/wakir/bin/wakir-persona-engine-recovery --version
/opt/wakir/bin/wakir-persona-engine-state-backing --version
/opt/wakir/bin/wakir-persona-engine-fsm --version
/opt/wakir/bin/wakir-persona-engine-v907-verify --version
/opt/wakir/bin/wakir-persona-engine-bridge-diff --version
/opt/wakir/bin/wakir-persona-engine-subscribe-loop --version
/opt/wakir/bin/wakir-persona-engine-anchor-emitter --version
```

## 5. Re-install / upgrade

The installer is idempotent on the bytes-level — re-running the
unit overwrites the seven binary files in `/opt/wakir/bin/` from
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
| Installer exits 2 with `missing or non-exec` | Carrier-image drift — the digest you have does NOT ship all seven binaries. Halt rollout, escalate to Zone-C cross-review (was the image rebuilt without one of the Tag-20/22/23 binaries?). |
| `/opt/wakir/bin/<binary> --version` segfaults on the host | Host glibc vs musl mismatch — the binaries are statically linked against musl per the persona-engine Containerfile.real; if this surfaces it indicates a build-substrate drift, not a Quadlet drift. Escalate to Selin / Rust-build-owner. |
| `systemctl status` reports `failed`, `journalctl` shows SELinux denial | The `:Z` relabel-private flag did not run (rare on FCOS but possible on incompletely-relabeled hosts). Run `restorecon -Rv /opt/wakir` and restart. |

## 8. Cross-substrate parity matrix

| Substrate | File | What it pins | Digest-source |
|---|---|---|---|
| Cosign-Policy | `policies/cosign-policy-phase-3b.yaml` | Carrier image + 7 binaries inventory | Operator-Hand resolve-image-pins-ci |
| Persona-tomas Quadlet | `quadlet/wakir-persona-tomas.container` | Carrier image (consumed in-container) | Operator-Hand resolve-image-pins-ci |
| **Rust-CLI installer Quadlet (Tag-22/24)** | `quadlet/wakir-rust-cli.container` | Carrier image + 7 binaries host-side install | Operator-Hand resolve-image-pins-ci |

All three substrates carry the same `DIGEST_PENDING_KAI_CROSS_REVIEW`
placeholder slot in the same byte-position, so a single
`resolve-image-pins-ci` run propagates the resolved digest into all
three files in lock-step.

## 9. Sandbox boundary

The hermetic test surface (`tests/infra/test_quadlets_phase_3b.py`)
validates the SHAPE of the Quadlet text — section headers, the seven
binaries listed, SELinux flags present, sha256 placeholder slot
canonical-form. No sandbox process calls `podman` or `systemctl`
against the host per `feedback_sandbox_host_trennung.md`. Live
bring-up is Operator-Hand per ADR-0051 Mira-Sandbox-vs-Host-
Operations-Trennung.

— Kai
