<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Cosign-Policy — Phase-3b Rust-CLI Binaries

**Status:** Living operations document.
**Scope:** The five Phase-3b Rust-CLI binaries that the
persona-engine production-default switch subprocess-bridges to
(`recovery`, `state-backing`, `fsm`, `v907-verify`, `bridge-diff`).
**Source of truth:** `policies/cosign-policy-phase-3b.yaml`.
**Sibling docs:** `infra/spire/federation/IMAGE_PINS.md` (SPIRE +
provisioner image pins), `docs/operations/branch-protection-required-status-checks.md`,
`docs/operations/quadlets-phase-3b-rust-cli.md` (Tag-22 Quadlet
installer; same 5-binary inventory).

---

## 1. Why this document exists

Phase-3b lands five ENV-gated subprocess-bridges from the
persona-engine Python orchestrator to compiled Rust-CLI binaries
(PRs #167, #169, #171, #175). The bridges live in
`wirelang/persona_engine/rust_backend_switch.py` and resolve to
the canonical paths
`/opt/wakir/bin/wakir-persona-engine-{recovery,state-backing,fsm,v907-verify,bridge-diff}`.
These five binaries are the **production-mode hot-path** when
operators flip `WAKIR_*_BACKEND=rust` in the Quadlet drop-in;
unverified binaries on that hot-path are a supply-chain breach.

> **Tag-23 Mini-Welle update.** Inventory extended from 4 to 5
> binaries; `bridge-diff` (Tag-20 PR #175) is now a first-class
> policy entry. The Tag-22 Quadlet installer
> (`quadlet/wakir-rust-cli.container`, PR #180) already iterated
> all five binaries; this update closes the cross-substrate
> inventory gap — both files now list the same five binaries
> byte-for-byte.

Cosign-policy answers two operator questions, both of which the
existing `IMAGE_PINS.md` substrate does NOT cover for the
Rust-CLI surface:

  * **Provenance** — which Sigstore identity (or static `cosign.pub`)
    am I asked to trust for these binaries? Answer: the GitHub-Actions
    OIDC identity of `.github/workflows/build-wakir-persona-engine.yml`.
  * **Boundary** — what counts as a verified install? Answer: the
    binaries ship inside the carrier image
    `ghcr.io/wakir-labs/wakir-persona-engine` at the canonical
    in-image paths declared in the policy YAML; verifying the
    keyless-signed image transitively verifies the binaries.

---

## 2. Policy file shape

`policies/cosign-policy-phase-3b.yaml` is the declarative substrate.
Three top-level sections:

  * **`policy:`** — names the Sigstore-keyless OIDC identity and the
    carrier image (tag + digest slot + build workflow + Containerfile).
  * **`binaries:`** — inventory of the five Rust-CLI binaries with
    crate path, in-image path, ENV-switch wiring, and the PR that
    landed each bridge.
  * **`verification:`** — three-step Operator-Hand recipe (cosign
    verify carrier image, crane cross-check digest, in-image
    binary-presence probe). Plus the `on_digest_mismatch:` posture.

The hermetic test surface (`tests/infra/test_cosign_policy_phase_3b.py`)
enforces the file SHAPE invariants — schema_version, all five
binaries present, sha256-slot canonical form, mismatch fixture
rejected.

---

## 3. Operator-Hand verification recipe

This section runs on a **host with registry network access and the
`cosign` + `crane` CLIs installed**, NOT in the claude-dev sandbox
(per `feedback_sandbox_host_trennung.md`).

### 3.1 Step 1 — cosign verify the carrier image

```sh
# Resolve the pinned digest from the policy YAML.
PINNED_DIGEST=$(awk '/expected_image_digest:/ {print $2; exit}' \
    policies/cosign-policy-phase-3b.yaml)
EXPECTED_TAG=$(awk '/expected_tag:/ {print $2; exit}' \
    policies/cosign-policy-phase-3b.yaml)

# Halt early if the digest is still the placeholder.
case "${PINNED_DIGEST}" in
    sha256:DIGEST_PENDING_KAI_CROSS_REVIEW)
        echo "halt: policy carries the placeholder digest; resolve first." >&2
        exit 1 ;;
esac

cosign verify \
    --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/wakir-labs/wakir-persona-engine:${EXPECTED_TAG}@${PINNED_DIGEST}
```

Expected output structure: see the canonical `cosign verify` shape
documented in `infra/spire/federation/IMAGE_PINS.md` §2.1. The
`critical.image.docker-manifest-digest` field MUST equal
`${PINNED_DIGEST}`.

### 3.2 Step 2 — crane digest cross-check

```sh
CRANE_DIGEST=$(crane digest \
    ghcr.io/wakir-labs/wakir-persona-engine:${EXPECTED_TAG})
echo "crane:  ${CRANE_DIGEST}"
echo "pinned: ${PINNED_DIGEST}"

if [ "${CRANE_DIGEST}" != "${PINNED_DIGEST}" ]; then
    echo "halt: registry digest drift; possible upstream re-push" >&2
    exit 2
fi
```

### 3.3 Step 3 — in-image binary-presence probe

The five binaries MUST be present at the canonical in-image paths
declared by `wirelang/persona_engine/rust_backend_switch.py`
(`DEFAULT_RUST_*_BIN` constants):

```sh
podman run --rm --entrypoint /bin/sh \
    ghcr.io/wakir-labs/wakir-persona-engine:${EXPECTED_TAG}@${PINNED_DIGEST} \
    -c 'set -e
        for b in /opt/wakir/bin/wakir-persona-engine-recovery \
                 /opt/wakir/bin/wakir-persona-engine-state-backing \
                 /opt/wakir/bin/wakir-persona-engine-fsm \
                 /opt/wakir/bin/wakir-persona-engine-v907-verify \
                 /opt/wakir/bin/wakir-persona-engine-bridge-diff; do
            test -x "$b" || { echo "missing or non-exec: $b" >&2; exit 2; }
        done
        echo OK'
```

If the carrier image is the Sprint-Pengine-13 `0.5.0-pilot` tag
(current inventory baseline), several of the five binaries will be
**present but not yet wired into a `[[bin]]`-target Cargo.toml
section** — the crates ship `[lib]` only as of Tag-19. The probe
above therefore expects the `[[bin]]`-promotion follow-up to land
before the policy moves out of the placeholder-digest state. The
test surface marks this expectation explicitly with a SKIP for the
live-probe path and a hard assertion on the policy-shape path.

The Tag-22 Quadlet installer (`quadlet/wakir-rust-cli.container`)
iterates the same five binaries in alphabetical-by-component order
(`bridge-diff`, `fsm`, `recovery`, `state-backing`, `v907-verify`);
the probe above iterates in landing-order. Both orderings are
acceptable — the contract is the *set* of five binaries, not the
iteration sequence.

---

## 4. On digest mismatch

If `cosign verify` rejects the signature OR if `crane digest`
returns a value that differs from the pinned digest:

  * **Halt the rollout.** Do not auto-resolve to the live digest.
    A mismatch is one of:
      - upstream key-rotation event (signed by a different OIDC
        identity than the policy expects),
      - tag re-push (registry serves a different digest under the
        same tag),
      - or a maliciously-signed image was pushed.
  * **Zone-C cross-review.** Tomás (Zone-C owner per `agents/kai.md`
    §"Vier Cross-Review-Zonen A-D") reviews the upstream signing
    event in the Sigstore Rekor transparency log against the
    GitHub-Actions OIDC identity of the build workflow.
  * **Do not edit the policy YAML to chase the new digest** until
    Zone-C cross-review concludes. The policy's
    `expected_image_digest` slot is the single source of truth; a
    silent edit defeats the supply-chain gate.

---

## 5. Phase-3b ENV-switch wiring

The five bridges live in `wirelang/persona_engine/rust_backend_switch.py`.
Each ENV-switch is closed-enum (rejects unknown values via
`BackendSwitchValidationError`):

| Component | ENV-switch | Valid values | Binary override ENV |
|---|---|---|---|
| recovery | `WAKIR_RECOVERY_BACKEND` | `python` (default), `rust` | `WAKIR_RUST_RECOVERY_BIN` |
| state-backing | `WAKIR_STATE_BACKING_BACKEND` | `python` (default), `rust_inmemory`, `rust_natskv` | `WAKIR_RUST_STATE_BACKING_BIN` |
| fsm | `WAKIR_FSM_BACKEND` | `python` (default), `rust` | `WAKIR_RUST_FSM_BIN` |
| v907-verify | `WAKIR_V907_VERIFY_BACKEND` | `python` (default), `rust` | `WAKIR_RUST_V907_VERIFY_BIN` |
| bridge-diff | `WAKIR_BRIDGE_DIFF_BACKEND` | `python` (default), `rust` | `WAKIR_RUST_BRIDGE_DIFF_BIN` |

Production-default stays Python on all five axes; opt-in via
Quadlet `Environment=` drop-in or `systemd-creds`. The
`fallback_reason` per-decision audit-record (structured JSON line,
default sink `/var/log/wakir/backend-decisions.jsonl`) is the
forensic anchor for "did the operator's `WAKIR_*_BACKEND=rust`
intent actually resolve to the Rust binary, or did the bridge
gracefully fall back to Python because the binary was missing?".
A `fallback_reason: missing_binary` line after a coordinated
cosign-policy resolution is a deployment bug, not a fallback —
the binary should be present in the image.

---

## 6. Air-gapped alternative — static `cosign.pub`

The Sigstore-keyless path requires Rekor reachability at verify
time. For air-gapped deployments (no outbound network to
`rekor.sigstore.dev`), an alternative path is:

  * Publish a static `policies/cosign.pub` containing the public
    key of the signing identity (operated by Wakir Labs).
  * Sign the carrier image at build time with
    `cosign sign --key cosign.key ghcr.io/.../wakir-persona-engine@<digest>`
    instead of the keyless OIDC path.
  * Verify with `cosign verify --key policies/cosign.pub` instead
    of the `--certificate-identity-regexp` + `--certificate-oidc-issuer`
    pair.

**This path is NOT the production default.** It exists as an
escape hatch for the air-gapped enterprise-deployment case. Both
paths are mutually exclusive — the same image MUST NOT be signed
under both modalities, because that would split the trust root.
If the air-gapped path is activated, the policy YAML's
`certificate_identity_regexp` + `certificate_oidc_issuer` fields
are replaced by a single `public_key_path: policies/cosign.pub`
field, and the hermetic test suite is extended to accept either
shape.

The static-key path also requires a rotation policy
(Wakir-Labs-side key custody, rotation interval, revocation
broadcast) which the Sigstore-keyless path delegates to GitHub-
Actions OIDC. This is the actual cost of the air-gapped path; the
Phase-3b default is keyless precisely to avoid carrying that
operational surface.

---

## 7. Cross-review zones touched by this policy

Per `agents/kai.md` §"Vier Cross-Review-Zonen A-D":

  * **Zone C — Container-Image-Pipeline x Tomás-OTS-Anchoring.**
    The carrier image (`wakir-persona-engine`) is on the same
    image-build pipeline that Tomás's OTS-anchoring chain already
    coordinates with; this policy adds the Rust-CLI binary
    surface as a first-class inventory item but does not change
    the image-build path or the digest-resolver workflow
    (`.github/workflows/resolve-image-pins-ci.yml`). No new
    Zone-C event; the Sprint-9 Tag-4 wakir-provisioner policy
    landed under the same posture.
  * **Zone D — Phala-Cloud-Setup x Reza-V-904-Identity-Bridge.**
    Phase-3b binaries are NOT in scope for V-904 / TEE-attestation
    yet — those land in Phase-3 substantive (V-904 Annex,
    ADR-0023b). The policy YAML's `schema_version` is bumped from
    `phase-3b/1` to `phase-3b+v904/1` (or successor) when the
    V-904 attestation surface lands; no field is removed in that
    bump, so this policy stays forward-compatible.

---

## 8. Cross-substrate parity — the 5-binary contract

Three substrate files now list the same five Phase-3b Rust-CLI
binaries; a drift between any two of them is a substrate breach
caught by the hermetic test surface:

| Substrate | File | Iteration order |
|---|---|---|
| Switch defaults | `wirelang/persona_engine/rust_backend_switch.py` | declaration-order (recovery, state-backing, fsm, v907-verify, bridge-diff, subscribe-loop) |
| Cosign-policy | `policies/cosign-policy-phase-3b.yaml` | landing-order (recovery, state-backing, fsm, v907-verify, bridge-diff) |
| Quadlet installer | `quadlet/wakir-rust-cli.container` | alphabetical-by-component (bridge-diff, fsm, recovery, state-backing, v907-verify) |

The contract is the **set** of five binaries, not the iteration
sequence. The hermetic tests
(`tests/infra/test_cosign_policy_phase_3b.py` for cosign-policy,
`tests/infra/test_quadlets_phase_3b.py` for the Quadlet) enforce
the set invariant on each side; a binary added to one substrate
without the other is rejected.

> **Note on `subscribe-loop`.** The Tag-22 Mini-Welle landed the
> `subscribe-loop` Rust bridge (PR #181, Tag-22 ENV-switch
> production-default flip; module-level constant
> `DEFAULT_RUST_SUBSCRIBE_LOOP_BIN`). The subscribe-loop binary
> is NOT yet in this Cosign-Policy because the Quadlet installer
> (PR #180) inventoried only the Tag-17-through-Tag-20 binaries.
> A subsequent Mini-Welle will extend BOTH substrates in lock-step
> to a 6-binary inventory — Cosign-Policy follows Quadlet here,
> so an out-of-sequence policy bump is rejected by the
> cross-substrate parity test in
> `tests/infra/test_quadlets_phase_3b.py`.

— Kai
