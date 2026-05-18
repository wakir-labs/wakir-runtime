<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Tag-45 Operator-Hand — Quadlet + Cosign 15-Binary Substrate Refresh

**Status:** Operator-Hand pre-cutover refresh recipe.
**Owner:** Kai Hoffmann (Dev-Engineering-3, Container-Orchestration).
**Cross-Review zones:** C (Container-Image-Pipeline x Tomás-OTS).
**Source of truth:** `policies/cosign-policy-phase-3b.yaml` (15-binary
inventory) and `quadlet/wakir-rust-cli.container` (11-carrier-image
binary installer Exec= loop).
**Sibling docs:**

  * `docs/operations/cosign-policy-phase-3b.md` — living Cosign-Policy
    operator reference.
  * `docs/operations/quadlets-phase-3b-rust-cli.md` — living Quadlet
    installer operator reference.
  * `docs/phase-3c/cutover-operator-cheat-sheet.md` — cross-Welle
    cutover orchestration.

---

## 1. Why this document exists

The Phase-3c cutover Mini-Welles (Welle-1..7) each pin a slice of the
Phase-3b Rust-CLI substrate; the carrier-image installer
(`quadlet/wakir-rust-cli.container`) and the Cosign-Policy
(`policies/cosign-policy-phase-3b.yaml`) are the two cross-Welle
substrates that EVERY cutover step depends on. A drift between them
is the worst failure mode in the Tag-22-vs-Tag-20 inventory-gap class
(one substrate copies a binary onto the host without a matching
verification gate, or advertises verification for a binary that the
installer does not actually deploy).

The Tag-45 Mini-Welle closes Reza's Phase-3a-Foundation 15-module sweep
by adding the canonical-trace bridges for:

  * `bridge-audit-replay` (Tag-37 PR #246 — 14. Modul;
    deterministic-replay-oracle canonical-trace from ADR-0063
    §Folgeartefakte Item 11).
  * `migrate-version` (Tag-38 PR #250 — 15. Modul; engine-version
    migration pre-flight decision canonical-trace; closes the
    Phase-3a-Foundation sweep at 15/15).

Both are CANONICAL-only bridges (no live state-backing I/O on the Rust
side; the Python sibling holds the live workflow, and the Rust binary
returns the canonical-trace projection for byte-paritätische
comparison). Both ship inside the carrier image (no dedicated
single-binary images — the Welle-4..7 dedicated-image convention
applies only to the cutover steps that need it).

The Tag-45 substrate-refresh keeps the carrier-image installer
(11 binaries) and the Cosign-Policy (15 binaries) in lock-step, so
when the Phase-3c cutover Welles consume either substrate they get a
consistent inventory.

---

## 2. Inventory delta — 7/13 -> 11/15

The two substrates now look like this:

| Substrate | File | Inventory size | Inventory order |
|---|---|---|---|
| Cosign-Policy | `policies/cosign-policy-phase-3b.yaml` | 15 (9 carrier + 4 Welle-4..7 dedicated + 2 Tag-45) | Landing order (Tag-17..Tag-45) |
| Quadlet installer | `quadlet/wakir-rust-cli.container` | 11 carrier-image binaries | Landing order in shell loop |
| Rust-backend-switch defaults | `wirelang/persona_engine/rust_backend_switch.py` | 11 `DEFAULT_RUST_*_BIN` constants | Declaration order |

### 2.1 The 15 Cosign-Policy entries

```
 1. recovery                       (Tag-17 PR #167)
 2. state-backing                  (Tag-17 PR #167)
 3. fsm                            (Tag-18 PR #169)
 4. v907-verify                    (Tag-19 PR #171)
 5. bridge-diff                    (Tag-20 PR #175)
 6. subscribe-loop                 (Tag-22 PR #181)
 7. anchor-emitter                 (Tag-23 PR #184)
 8. svid-workload-identity         (Tag-25 PR #191 + Tag-29 crate)
 9. bridge-audit-writer            (Tag-31)
10. state-backing-welle4           (Tag-33 dedicated single-binary)
11. fsm-welle5                     (Tag-33 dedicated single-binary)
12. subscribe-loop-welle6          (Tag-33 dedicated single-binary)
13. recovery-welle7                (Tag-33 dedicated single-binary)
14. bridge-audit-replay            (Tag-37 PR #246 — Tag-45 promotes)
15. migrate-version                (Tag-38 PR #250 — Tag-45 ships)
```

### 2.2 The 11 carrier-image binaries (Quadlet installer Exec= loop)

The four Welle-4..7 dedicated single-binary images are NOT installed
by `wakir-rust-cli.container`; they have their own per-Welle Quadlets
that the cutover Mini-Wellen land independently. The Quadlet installer
iterates the 11 binaries that ship inside the carrier image at the
canonical `/opt/wakir/bin/wakir-persona-engine-<component>` paths:

```
 1. wakir-persona-engine-recovery
 2. wakir-persona-engine-state-backing
 3. wakir-persona-engine-fsm
 4. wakir-persona-engine-v907-verify
 5. wakir-persona-engine-bridge-diff
 6. wakir-persona-engine-subscribe-loop
 7. wakir-persona-engine-anchor-emitter
 8. wakir-persona-engine-svid-workload-identity
 9. wakir-persona-engine-bridge-audit-writer
10. wakir-persona-engine-bridge-audit-replay        (Tag-45 addition)
11. wakir-persona-engine-migrate-version            (Tag-45 addition)
```

---

## 3. Installer-Sequence

Operator-Hand on a Pilot-VM host with `cosign` + `crane` + `podman`
+ `systemctl` available. The sequence is idempotent — running it
twice produces the same result; running it after a partial earlier
attempt picks up from where the previous run left off (Step 1 +
Step 2 are pure verification; Step 3 + Step 4 are idempotent).

### 3.1 Step 1 — Verify Cosign-Policy is at Tag-45 inventory

```bash
# Sanity-check the policy file is at the Tag-45 15-binary inventory.
POLICY=policies/cosign-policy-phase-3b.yaml
test -f "${POLICY}" || { echo "halt: policy file missing"; exit 1; }

POLICY_BINARY_COUNT=$(grep -cE '^\s*-\s+name:' "${POLICY}")
if [ "${POLICY_BINARY_COUNT}" -ne 15 ]; then
    echo "halt: policy has ${POLICY_BINARY_COUNT} binaries; expected 15." >&2
    exit 1
fi

# The two Tag-45 additions must be present.
for name in bridge-audit-replay migrate-version; do
    grep -qE "^\s+-\s+name:\s+${name}\s*$" "${POLICY}" \
        || { echo "halt: ${name} missing from policy"; exit 1; }
done
echo "OK: policy at Tag-45 15-binary inventory."
```

### 3.2 Step 2 — Cosign-verify the carrier image (15-binary policy gate)

```bash
PINNED_DIGEST=$(awk '/expected_image_digest:/ {print $2; exit}' \
    policies/cosign-policy-phase-3b.yaml)
EXPECTED_TAG=$(awk '/expected_tag:/ {print $2; exit}' \
    policies/cosign-policy-phase-3b.yaml)

case "${PINNED_DIGEST}" in
    sha256:DIGEST_PENDING_KAI_CROSS_REVIEW)
        echo "halt: policy carries placeholder digest; resolve first." >&2
        exit 1 ;;
esac

cosign verify \
    --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/wakir-labs/wakir-persona-engine:${EXPECTED_TAG}@${PINNED_DIGEST}

CRANE_DIGEST=$(crane digest \
    ghcr.io/wakir-labs/wakir-persona-engine:${EXPECTED_TAG})
[ "${CRANE_DIGEST}" = "${PINNED_DIGEST}" ] \
    || { echo "halt: registry digest drift"; exit 2; }
```

### 3.3 Step 3 — In-image 11-binary presence probe

```bash
podman run --rm --entrypoint /bin/sh \
    ghcr.io/wakir-labs/wakir-persona-engine:${EXPECTED_TAG}@${PINNED_DIGEST} \
    -c 'set -e
        for b in /opt/wakir/bin/wakir-persona-engine-recovery \
                 /opt/wakir/bin/wakir-persona-engine-state-backing \
                 /opt/wakir/bin/wakir-persona-engine-fsm \
                 /opt/wakir/bin/wakir-persona-engine-v907-verify \
                 /opt/wakir/bin/wakir-persona-engine-bridge-diff \
                 /opt/wakir/bin/wakir-persona-engine-subscribe-loop \
                 /opt/wakir/bin/wakir-persona-engine-anchor-emitter \
                 /opt/wakir/bin/wakir-persona-engine-svid-workload-identity \
                 /opt/wakir/bin/wakir-persona-engine-bridge-audit-writer \
                 /opt/wakir/bin/wakir-persona-engine-bridge-audit-replay \
                 /opt/wakir/bin/wakir-persona-engine-migrate-version; do
            test -x "$b" || { echo "missing or non-exec: $b" >&2; exit 2; }
        done
        echo "OK: 11/11 carrier-image binaries present and executable"'
```

If the carrier image is the Sprint-Pengine-13 `0.5.0-pilot` tag and
the two Tag-45 additions are present-but-not-yet-built-as-[[bin]]-
targets, the probe will fail with `missing or non-exec` on the new
binaries. This is the expected `[[bin]]`-promotion follow-up gate
(see §6 Bin-Target-Promotion Notes).

### 3.4 Step 4 — Install / re-install the carrier-image installer Quadlet

```bash
# Install the unit + named-volume (idempotent overwrite).
sudo install -m 644 quadlet/wakir-rust-cli.container \
    /etc/containers/systemd/wakir-rust-cli.container
sudo install -m 644 quadlet/wakir-rust-cli-bin.volume \
    /etc/containers/systemd/wakir-rust-cli-bin.volume

# Pre-create the host-side install location with the right SELinux
# context.
sudo install -d -m 755 /opt/wakir/bin

# Reload + (re-)start. The oneshot exits 0 after install completes;
# RemainAfterExit=yes keeps the unit "active" so dependent units can
# Require= it.
sudo systemctl daemon-reload
sudo systemctl start wakir-rust-cli.service

# Verify all 11 binaries landed on the host side.
sudo systemctl status wakir-rust-cli.service --no-pager
ls -l /opt/wakir/bin/wakir-persona-engine-{recovery,state-backing,fsm,v907-verify,bridge-diff,subscribe-loop,anchor-emitter,svid-workload-identity,bridge-audit-writer,bridge-audit-replay,migrate-version}
```

The Quadlet `Exec=` line carries an explicit `set -e` + binary-
presence-probe, so a missing carrier-image binary surfaces as a
oneshot exit-code-2 — `systemctl status` will show the failure and
the journal will carry the offending binary name.

---

## 4. Cosign-Verification — per-binary gate

The carrier image is keyless-signed and the policy verifies the
image; the 11 binaries inside are transitively verified by the
image gate. There is NO per-binary cosign signature in Phase-3b
(see ADR-0034 / Sprint-9-Tag-4 wakir-provisioner posture). The
per-binary "verification" is the in-image-presence probe in §3.3.

For the Tag-45 additions specifically:

  * `bridge-audit-replay` — Cosign-Policy entry `bridge-audit-replay`,
    in-image path `/opt/wakir/bin/wakir-persona-engine-bridge-audit-replay`,
    env-switch `WAKIR_BRIDGE_AUDIT_REPLAY_BACKEND=rust`, binary override
    `WAKIR_RUST_BRIDGE_AUDIT_REPLAY_BIN`.
  * `migrate-version` — Cosign-Policy entry `migrate-version`,
    in-image path `/opt/wakir/bin/wakir-persona-engine-migrate-version`,
    env-switch `WAKIR_MIGRATE_VERSION_BACKEND=rust`, binary override
    `WAKIR_RUST_MIGRATE_VERSION_BIN`.

The cross-substrate parity test
(`tests/infra/test_cosign_policy_phase_3b.py::test_cross_substrate_parity_with_quadlet_installer`)
enforces the agreement at PR-author time: a binary added to the
policy without a matching Exec= loop entry (or vice versa) is
rejected before merge.

---

## 5. Rollback-Pfad pro Binary

The carrier-image binaries are oneshot-installed; rolling back is
delete-from-host + restart the dependent unit:

### 5.1 Rollback all 11 binaries (full revert)

```bash
sudo systemctl stop wakir-rust-cli.service
sudo systemctl disable wakir-rust-cli.service 2>/dev/null || true

# Remove the Quadlet units.
sudo rm -f /etc/containers/systemd/wakir-rust-cli.container
sudo rm -f /etc/containers/systemd/wakir-rust-cli-bin.volume

# Optional: full purge of the host-side install.
sudo rm -rf /opt/wakir/bin/wakir-persona-engine-*
sudo podman volume rm wakir-rust-cli-bin 2>/dev/null || true

# Reload systemd so dependent units see the units are gone.
sudo systemctl daemon-reload
```

### 5.2 Rollback a single binary (selective revert)

For a partial rollback (e.g. the new `migrate-version` is segfaulting
on a specific host kernel; keep the other 10 installed):

```bash
# 1. Remove the offending binary from the host.
sudo rm -f /opt/wakir/bin/wakir-persona-engine-migrate-version

# 2. Flip the corresponding ENV-switch back to python in the
#    persona-engine Quadlet drop-in. Example:
sudo mkdir -p /etc/containers/systemd/wakir-persona-tomas.container.d
sudo tee /etc/containers/systemd/wakir-persona-tomas.container.d/migrate-version-rollback.conf <<EOF
[Container]
Environment=WAKIR_MIGRATE_VERSION_BACKEND=python
EOF

# 3. Reload + restart the consumer unit.
sudo systemctl daemon-reload
sudo systemctl restart wakir-persona-tomas.service
```

The `fallback_reason: missing_binary` audit-record line will appear
in `/var/log/wakir/backend-decisions.jsonl` on the next subprocess-
bridge invocation. That line is operator-readable confirmation
that the rollback flipped the bridge back to the Python sibling.

### 5.3 Rollback specifically the Tag-45 additions (the 11->9 path)

If the Tag-45 substrate-refresh exposes a regression in either of
the two new bridges, the carrier-image installer can be reverted
to the Tag-31 9-binary inventory without touching the rest of the
substrate. The selective-revert path is:

```bash
# 1. Reinstall the Tag-31 carrier-image Quadlet (cherry-pick).
git checkout 8df7e7c -- quadlet/wakir-rust-cli.container
sudo install -m 644 quadlet/wakir-rust-cli.container \
    /etc/containers/systemd/wakir-rust-cli.container

# 2. Reload + restart. The oneshot will re-install only the 9 Tag-31
#    binaries; the two Tag-45 binaries already on the host stay until
#    a full purge.
sudo systemctl daemon-reload
sudo systemctl restart wakir-rust-cli.service

# 3. Flip the two Tag-45 ENV-switches back to python.
sudo tee /etc/containers/systemd/wakir-persona-tomas.container.d/tag45-rollback.conf <<EOF
[Container]
Environment=WAKIR_BRIDGE_AUDIT_REPLAY_BACKEND=python
Environment=WAKIR_MIGRATE_VERSION_BACKEND=python
EOF
sudo systemctl daemon-reload
sudo systemctl restart wakir-persona-tomas.service
```

The Cosign-Policy stays at the Tag-45 15-binary inventory — it is
forward-compatible (the Tag-31 Quadlet does not deploy the two
extra binaries, but the policy still verifies the carrier image
that ships them; the cross-substrate parity test will red for the
duration of the rollback, which is the operator-visible signal
that the rollback is in progress).

---

## 6. Bin-Target-Promotion Notes

The Tag-45 Cosign-Policy additions assume the two new binaries ship
inside the carrier image at the canonical paths. The Rust crate
state as of `8df7e7c`:

  * `persona-engine-bridge-audit-replay` — ships `[[bin]]` targets
    `replay_cli` and `wakir-persona-engine-bridge-audit-writer`.
    A future Mini-Welle adds a `wakir-persona-engine-bridge-audit-replay`
    `[[bin]]` target wrapping the canonical-trace projection
    (`bridge_audit_replay_canonical.rs`); this is the Tag-45 Cosign-
    Policy entry's binary.
  * `persona-engine-migrate-version` — ships `[lib]` only; a future
    Mini-Welle adds a `wakir-persona-engine-migrate-version` `[[bin]]`
    target wrapping the canonical-trace projection.

Until those `[[bin]]` targets land, the Step-3 probe will red on
the two new entries. This is the EXPECTED state for the Tag-45
substrate-refresh — the policy and the installer are pre-positioned
for the carrier-image build that lands the binaries, and the
hermetic tests enforce the substrate invariants without depending
on the live binary build state.

The `[[bin]]`-promotion follow-up is tracked separately (Reza-side
or Selin-side; not in scope for Tag-45 Kai substrate-refresh).

---

## 7. Cross-Welle-Coordination

The 11-binary carrier-image installer is the common substrate for
all Phase-3c cutover Mini-Wellen (Welle-1..7). The coordination
contract is:

  * **Welle-1..3 (already landed pre-Tag-45):** consume the 9-binary
    carrier-image set. The Tag-45 11-binary upgrade does NOT break
    Welle-1..3 cutover smoke tests (the smoke tests probe only the
    binaries each Welle pins; additional binaries on the host are
    not a regression).
  * **Welle-4..7 (in-flight / pre-cutover at Tag-45):** consume both
    the 11-binary carrier-image set AND the four Welle-4..7
    dedicated single-binary images (`state-backing-welle4`,
    `fsm-welle5`, `subscribe-loop-welle6`, `recovery-welle7`).
    The dedicated-image Quadlets are landed by the respective
    Mini-Wellen, not by this installer.
  * **Engine-version migration step (post-Welle-7):** consumes the
    Tag-45 `migrate-version` binary. The migration step runs as a
    pre-flight gate before any state-backing I/O; if the Rust binary
    is missing, the bridge falls back to the Python sibling (the
    `fallback_reason: missing_binary` audit-record line is the
    operator-readable signal).
  * **Phase-3a Doppelbetrieb consistency drill (deterministic-replay
    oracle):** consumes the Tag-45 `bridge-audit-replay` binary. The
    drill compares the canonical-trace projections from both engines
    (Python sibling + Rust subprocess-bridge); a missing Rust binary
    forces the drill to single-language mode (operator-readable as
    `oracle_mode: python-only` in the drill report).

The cross-substrate parity test
(`tests/infra/test_cosign_policy_phase_3b.py::test_cross_substrate_parity_with_quadlet_installer`)
enforces the contract at PR-author time. The hermetic test surface
(`tests/infra/test_tag45_quadlet_cosign_15_binary_substrate.py`,
new at Tag-45) extends the invariant coverage with the 12+ tests
listed in `§8` below.

---

## 8. Tag-45 Hermetic Test Surface

The Tag-45 substrate-refresh ships with a dedicated hermetic test
module (`tests/infra/test_tag45_quadlet_cosign_15_binary_substrate.py`)
covering 12 invariants:

  1. `test_policy_at_15_binary_inventory` — the policy lists exactly
     15 binary entries.
  2. `test_quadlet_installer_at_11_binary_carrier_image` — the
     installer Exec= shell loop iterates exactly 11 carrier-image
     binary basenames.
  3. `test_tag45_additions_present_in_policy` — both
     `bridge-audit-replay` and `migrate-version` are first-class
     policy entries with the required-keys shape.
  4. `test_tag45_additions_present_in_quadlet_exec_loop` — both
     Tag-45 binary basenames appear in the Exec= shell loop.
  5. `test_tag45_additions_have_default_rust_bin_constants` — both
     `DEFAULT_RUST_BRIDGE_AUDIT_REPLAY_BIN` and
     `DEFAULT_RUST_MIGRATE_VERSION_BIN` are declared in
     `rust_backend_switch.py` and resolve to canonical
     `/opt/wakir/bin/` paths matching the policy entries.
  6. `test_tag45_env_switches_documented_in_operations_doc` — both
     `WAKIR_BRIDGE_AUDIT_REPLAY_BACKEND` and
     `WAKIR_MIGRATE_VERSION_BACKEND` appear in the operations doc
     §5 wiring table.
  7. `test_tag45_in_image_paths_match_quadlet_install_loop` — for
     each Tag-45 binary the in-image path from the policy matches
     the basename in the Quadlet Exec= loop.
  8. `test_tag45_crate_paths_exist_on_disk` — the `crate_path`
     entries for both Tag-45 binaries point at directories that
     exist on disk and carry a `Cargo.toml`.
  9. `test_tag45_carrier_image_set_is_11_not_15` — only the 11
     carrier-image binaries appear in the Quadlet installer; the
     four Welle-4..7 dedicated single-binary images are NOT in the
     installer (they have their own per-Welle Quadlets).
 10. `test_tag45_recipe_doc_present_and_anchors_policy` — the
     Tag-45 recipe doc
     (`docs/phase-3c/quadlet-cosign-15-binary-installer.md`) exists
     and anchors on the policy YAML + the two Tag-45 binary names.
 11. `test_tag45_landed_pr_anchors_correct` — the Tag-45 policy
     entries anchor on the right PR numbers (#246 for
     bridge-audit-replay, #250 for migrate-version).
 12. `test_tag45_sandbox_boundary_stamp_preserved` — the policy
     file still carries the sandbox-host-trennung stamp after the
     Tag-45 inventory bump (no run_in_sandbox: true regression).

Each test is hermetic — no `podman`, no `cosign`, no `crane`, no
`systemctl` invocations. Live verification is Operator-Hand per
`feedback_sandbox_host_trennung.md`. The 12-test surface satisfies
the Tag-45 auftrag floor ("mind. 12 hermetic Tests").

---

## 9. Cross-Review Anchors

Per `agents/kai.md` §"Vier Cross-Review-Zonen A-D":

  * **Zone C — Container-Image-Pipeline x Tomás-OTS-Anchoring.**
    Same carrier image, same image-build pipeline as the prior 13
    policy entries. No new Zone-C event; the Tag-45 substrate-
    refresh is a pure inventory extension on the same digest-resolver
    workflow (`.github/workflows/resolve-image-pins-ci.yml`).
    The two new bridges (canonical-only — no live I/O) do not
    introduce any new image-build surface; the carrier image ships
    them via the existing Containerfile.real
    (`infra/persona-engine/Containerfile.real`) once the
    `[[bin]]`-promotion follow-up lands.

  * **Zone D — Phala-Cloud-Setup x Reza-V-904-Identity-Bridge.**
    Phase-3a Modul 14 + 15 are canonical-trace bridges; they do not
    touch the V-904 attestation surface. No Zone-D event.

---

## 10. Sandbox boundary

NO sandbox process calls `cosign`, `crane`, `skopeo`, `podman`, or
`systemctl` against the host. Live verification (Steps 3.2 - 3.4
above) is Operator-Hand per `feedback_sandbox_host_trennung.md` +
ADR-0051 Mira-Sandbox-vs-Host-Operations-Trennung. The hermetic
test surface (`tests/infra/test_tag45_quadlet_cosign_15_binary_substrate.py`)
reads files on disk only.

— Kai
