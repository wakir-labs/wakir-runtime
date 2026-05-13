# SPIRE-Federation Image-Pins

**Status:** Operator-Hand resolution pending. Sandbox does NOT touch
GHCR per [`feedback_sandbox_host_trennung.md`][sandbox-trennung].

[sandbox-trennung]: ../../../../.claude/feedback_sandbox_host_trennung.md

This file is the Phase-2 Sprint-8 Tag-4 SINGLE-SOURCE-OF-TRUTH index
for SPIRE image-pins used by the Federation substrate. Operator-Hand
resolves each placeholder by running `cosign verify` + a digest-
resolver (`crane`, `skopeo`, or `cosign triangulate`) and substituting
all occurrences of the placeholder token across the listed files.

## 1. Pinned images

| Image | Tag | Placeholder | Files |
|---|---|---|---|
| `ghcr.io/spiffe/spire-server` | `1.14.6` | `sha256:DIGEST_PENDING_TOMAS_REVIEW` | `compose/spire-federation.yaml` (×2), `quadlet/wakir-spire-server-federation.container` |
| `ghcr.io/spiffe/spire-agent` | `1.14.6` | `sha256:DIGEST_PENDING_TOMAS_REVIEW` | `compose/spire-agent-federation.yaml` (×2), `quadlet/wakir-spire-agent-federation.container` |
| `docker.io/library/python` | `3.13-slim` | `sha256:DIGEST_PENDING_TOMAS_REVIEW` | `infra/spire/federation/provisioner/Containerfile` (base layer for `wakir-provisioner`) |
| `ghcr.io/wakir-labs/wakir-provisioner` | `0.1.1` | `sha256:DIGEST_PENDING_TOMAS_REVIEW` | `quadlet/wakir-nats-kv-bucket-init.container` |

SPIRE-Server and SPIRE-Agent MUST stay version-parity: SPIRE upstream
releases the server and agent as a paired binary set, and version-skew
between the two has been observed to break federation-bundle handshake
in prior upstream releases.

The `python:3.13-slim` image is the BASE LAYER for the
`wakir-provisioner` image (Sprint-9 Tag-4, see
`infra/spire/federation/provisioner/`). Until Sprint-9 Tag-4 the
Quadlet `wakir-nats-kv-bucket-init.container` referenced
`python:3.13-slim` directly; the Tag-1 author-time assumption that
the slim image ships `nats-py` was incorrect, and the Pilot-VM
bring-up on 2026-05-13 surfaced the gap as
`ModuleNotFoundError: No module named 'cryptography'` (the
provisioner's transitive imports through `wirelang.identity` also
require `cryptography`, which the slim image does not carry). The
`wakir-provisioner` image is the substitute substrate. The v0.1.0
image carried four wheels (`nats-py`, `cryptography`, `rfc8785`,
`jsonschema`) to satisfy the provisioner's transitive imports
through `wirelang.identity`. After Reza-PR #33
(Wirelang-Import-Disentanglement, PEP-562 lazy `__getattr__` on
`wirelang.federation`), the transitive identity-stack import chain
no longer fires for the marker-stack-kv / sequence-number-ledger
code paths the provisioner exercises, and the v0.1.1 image shrinks
the wheel set to `nats-py` only. Both versions ship under Apache-2.0
with hash-pinned build inputs
(`infra/spire/federation/provisioner/requirements.txt`).

Both layers stay digest-pinned: the base-image pin lives in the
`provisioner/Containerfile` `FROM` line and resolves via the
DockerHub recipe in §2.4; the published Wakir image pin lives in
`quadlet/wakir-nats-kv-bucket-init.container` and resolves via the
Sigstore-keyless recipe in §2.5.

## 2. Operator-Hand resolution recipe

### 2.1 Verify upstream image with cosign

```sh
# spire-server
cosign verify \
    --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/spiffe/spire-server:1.14.6

# spire-agent
cosign verify \
    --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/spiffe/spire-agent:1.14.6
```

Expected output (per `cosign verify` v2.x — exact JSON field set
varies by cosign release):

```
Verification for ghcr.io/spiffe/spire-server:1.14.6 --
The following checks were performed on each of these signatures:
  - The cosign claims were validated
  - Existence of the claims in the transparency log was verified offline
  - The code-signing certificate was verified using trusted certificate authority certificates

[
  {
    "critical": {
      "identity": {
        "docker-reference": "ghcr.io/spiffe/spire-server"
      },
      "image": {
        "docker-manifest-digest": "sha256:<64-hex>"
      },
      "type": "cosign container image signature"
    },
    ...
  }
]
```

The `docker-manifest-digest` field is the canonical digest to pin.

### 2.2 Resolve digest separately (cross-check)

`cosign verify` already prints the digest in the `critical.image`
field. A second, independent resolver as cross-check:

```sh
# Via skopeo
skopeo inspect docker://ghcr.io/spiffe/spire-server:1.14.6 \
    | jq -r '.Digest'
skopeo inspect docker://ghcr.io/spiffe/spire-agent:1.14.6 \
    | jq -r '.Digest'

# Via crane (Google's go-containerregistry CLI)
crane digest ghcr.io/spiffe/spire-server:1.14.6
crane digest ghcr.io/spiffe/spire-agent:1.14.6
```

Both digests MUST match the `docker-manifest-digest` from
`cosign verify`. If they DON'T match, refuse to pin — possible tag
re-push event upstream, requires Tomás Zone-C cross-review.

### 2.3 Substitute placeholders (single edit, multi-file)

```sh
# After resolution, with the digests captured in env vars:
SERVER_DIGEST=sha256:<64-hex-of-server>
AGENT_DIGEST=sha256:<64-hex-of-agent>

# Server-side substitution (compose + quadlet):
sed -i "s|spire-server:1.14.6@sha256:DIGEST_PENDING_TOMAS_REVIEW|spire-server:1.14.6@${SERVER_DIGEST}|g" \
    infra/spire/federation/compose/spire-federation.yaml \
    infra/spire/federation/quadlet/wakir-spire-server-federation.container

# Agent-side substitution (compose + quadlet):
sed -i "s|spire-agent:1.14.6@sha256:DIGEST_PENDING_TOMAS_REVIEW|spire-agent:1.14.6@${AGENT_DIGEST}|g" \
    infra/spire/agent/compose/spire-agent-federation.yaml \
    infra/spire/agent/quadlet/wakir-spire-agent-federation.container

# Re-run the hermetic test surface to confirm no syntax break:
pytest infra/spire/federation/tests/ infra/spire/agent/tests/

# Commit (single commit, both server + agent):
git add infra/spire/federation infra/spire/agent
git commit -m "chore(spire): pin federation images to verified digests"
```

The hermetic test `test_image_pin_digest_form.py` enforces that ALL
four files use either the placeholder token `DIGEST_PENDING_TOMAS_
REVIEW` OR a 64-hex sha256 digest. A half-resolved state (server
pinned, agent placeholder) is flagged by the test as a Phase-2 image-
pin invariant breach.

### 2.4 python:3.13-slim — DockerHub OCI resolution (base layer)

Added in Phase-2 Sprint-9 Tag-3 alongside the per-org NATS-KV bucket
provisioner Quadlet (ADR-0048); re-targeted in Sprint-9 Tag-4 from
the Quadlet directly to the `wakir-provisioner` image's
`Containerfile` base layer (the Tag-1/3 direct-consume path
surfaced as Bug 6 on the Pilot-VM bring-up). The `python:3.13-slim`
image is published on DockerHub, not on the Sigstore-backed GHCR
path used by SPIRE. The resolution path is a plain manifest-digest
lookup (`cosign verify` against a Sigstore identity is NOT
available, because Docker Official Images are not Sigstore-signed
as of 2026-05-13 — DockerHub publishes a content-trust signature
via Notary v1, which is end-of-life upstream, so we do not rely on
it). The Operator-Hand recipe is a two-resolver cross-check:

```sh
# Step 1: resolve the digest via skopeo (manifest-list aware).
PYTHON_DIGEST=$(skopeo inspect docker://python:3.13-slim | jq -r '.Digest')
echo "${PYTHON_DIGEST}"   # sha256:<64-hex>

# Step 2 (defence-in-depth): cross-check with `crane digest`.
crane digest python:3.13-slim
# must equal ${PYTHON_DIGEST}.

# Step 3: substitute the placeholder in the referencing Containerfile.
sed -i "s|python:3.13-slim@sha256:DIGEST_PENDING_TOMAS_REVIEW|python:3.13-slim@${PYTHON_DIGEST}|g" \
    infra/spire/federation/provisioner/Containerfile

# Step 4: re-run the hermetic test surface (python-pin tests).
pytest infra/spire/federation/provisioner/tests/test_containerfile.py
```

Cross-arch note: `python:3.13-slim` is a manifest-list (multi-arch).
The `skopeo inspect` call above returns the digest of the
**manifest-list**, which is the right pin form for a host-pull that
delegates arch-selection to Podman. Operators who want to pin to a
single arch can use `skopeo inspect --raw docker://python:3.13-slim`
and select the per-arch manifest by hand — but pilot deployments stay
on the manifest-list digest for portability across the Phase-1b
Proxmox-x86_64 + future-ARM mixed inventory.

Drift-alarm: an unannounced re-push of a Docker Official Image is
a community-relevant supply-chain event; if `skopeo inspect` returns
a digest that does NOT match a previously-pinned value, halt the
rollout and Zone-C cross-review the upstream announcement (Docker
Library GitHub release notes + Python release notes).

### 2.5 wakir-provisioner — GHCR Sigstore-keyless resolution

Added in Phase-2 Sprint-9 Tag-4. The `wakir-provisioner` image is
published by Wakir Labs to GHCR
(`ghcr.io/wakir-labs/wakir-provisioner`); it is built from
`infra/spire/federation/provisioner/Containerfile` against the
hash-pinned wheel set in
`infra/spire/federation/provisioner/requirements.txt`. The build
runs in the workflow_dispatch-only
`.github/workflows/build-wakir-provisioner.yml`; the resulting
digest is signed keyless via Sigstore against the GitHub-Actions
OIDC identity of the runner.

Operator-Hand resolution recipe:

```sh
# Step 1: build the image on a build host (see
#         infra/spire/federation/provisioner/README.md §3 for the
#         full recipe including base-image digest resolution and
#         hash-pinned wheel install).

# Step 2: cosign verify against the GitHub-Actions OIDC identity
#         of the build workflow.
cosign verify \
    --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/wakir-labs/wakir-provisioner:0.1.1

# Step 3: resolve the digest via crane (cross-check).
PROVISIONER_DIGEST=$(crane digest ghcr.io/wakir-labs/wakir-provisioner:0.1.1)
echo "${PROVISIONER_DIGEST}"   # sha256:<64-hex>

# Step 4: substitute the placeholder in the Quadlet.
sed -i "s|wakir-provisioner:0.1.1@sha256:DIGEST_PENDING_TOMAS_REVIEW|wakir-provisioner:0.1.1@${PROVISIONER_DIGEST}|g" \
    quadlet/wakir-nats-kv-bucket-init.container

# Step 5: re-run the hermetic test surface.
pytest tests/infra/test_wakir_provisioner_image_pin_form.py
```

Why this image and not `python:3.13-slim` directly? See the §1
table notes — the Tag-1 author-time assumption that the slim image
ships `nats-py` was incorrect, and the Pilot-VM bring-up surfaced
the gap as `ModuleNotFoundError`. The `wakir-provisioner` image is
the substrate that closes the wheel-availability gap in a single
supply-chain artifact, hash-pinned at build time and digest-pinned
at pull time.

## 3. CI integration (optional, Phase-2 Sprint-8 Tag-4 follow-up)

A CI job can run `cosign verify` as a pre-build gate. Sketch:

```yaml
# .github/workflows/cosign-verify-federation.yml (Phase-2 Sprint-8
# Tag-4 follow-up — Operator-Hand activation, gated on Tomás Zone-C
# cross-review for the GHCR-network-access policy).
jobs:
  cosign-verify-spire-images:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: sigstore/cosign-installer@v3
      - name: Verify spire-server image
        run: |
          cosign verify \
            --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
            --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
            ghcr.io/spiffe/spire-server:1.14.6
      - name: Verify spire-agent image
        run: |
          cosign verify \
            --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
            --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
            ghcr.io/spiffe/spire-agent:1.14.6
      - name: Refuse merge if digests drift from pinned values
        run: |
          # Extract pinned digests from the compose files and compare
          # to live cosign-verified digests. (Implementation detail
          # of the Tomás Zone-C follow-up.)
          echo "TODO Phase-2 Sprint-8 Tag-4 follow-up"
```

Activation is **gated on Tomás Zone-C cross-review** for two reasons:

  * The CI job pulls from GHCR on every PR — this is a supply-chain
    network egress that needs the same Zone-C approval as the image-
    pin itself.

  * A failing `cosign verify` on a previously-pinned digest is an
    upstream-key-rotation event; the response is NOT "auto-update the
    pin" but "halt merges + Tomás reviews the upstream signing event".

## 4. Sandbox boundary

This sandbox (claude-dev) MUST NOT call `cosign`, `skopeo`, or `crane`
against `ghcr.io` or `docker.io` per
`feedback_sandbox_host_trennung.md`. The hermetic test surface
validates the placeholder/digest SYNTAX only — the live verification
is Operator-Hand on a host that has registry network access and the
`cosign` / `skopeo` / `crane` CLIs installed.

— Kai

## 5. Sprint-9 Tag-3 follow-up (Tomás)

- Added `python:3.13-slim` to the inventory (§1, §2.4) so the
  Sprint-9 Tag-1 per-org NATS-KV bucket-init Quadlet stays in scope
  for the Zone-C cross-review.
- Promoted the §3 CI sketch into a real workflow file at
  `.github/workflows/cosign-verify-images.yml`, gated on
  `workflow_dispatch` so it remains Operator-Hand-only until the
  Zone-C GHCR-network-egress policy is approved.
- Added a hermetic test for the python pin form at
  `tests/infra/test_python_image_pin_form.py` mirroring the
  SPIRE-pin hermetic invariants.

— Tomás

## 6. Sprint-9 Tag-4 follow-up (Tomás) — Bucket-Init Bug-Fix-Welle

Driver: Mira-Bug-Bilanz 2026-05-13, Bug 6
(`agents-workspaces/mira/outbox/2026-05-13-pilot-bringup-bug-bilanz.md`).
Pilot-VM bring-up crashed at unit start with
`ModuleNotFoundError: No module named 'cryptography'` because the
Tag-1 author-time assumption that `python:3.13-slim` ships `nats-py`
was incorrect (the slim image ships the CPython stdlib only).

Tag-4 substrate:

- Added `ghcr.io/wakir-labs/wakir-provisioner` to the inventory
  (§1, §2.5). The v0.1.0 image carried four wheels (`nats-py`,
  `cryptography`, `rfc8785`, `jsonschema`) to satisfy the
  provisioner's transitive imports through `wirelang.identity`.
  After Reza-PR #33 (Wirelang-Import-Disentanglement, PEP-562 lazy
  `__getattr__` on `wirelang.federation`), the transitive identity-
  stack import chain no longer fires for the marker-stack-kv /
  sequence-number-ledger code paths the provisioner exercises. The
  v0.1.1 image (current inventory tag) shrinks the wheel set to
  `nats-py` only. Build inputs are hash-pinned in
  `infra/spire/federation/provisioner/requirements.txt`.
- Re-targeted the `python:3.13-slim` pin (§2.4) from the Quadlet
  directly to the `wakir-provisioner` Containerfile's `FROM` line.
  The base-layer pin retains its DockerHub-skopeo+crane resolver
  recipe; the published-image pin (§2.5) adds the
  Sigstore-keyless resolver recipe.
- Updated the consuming Quadlet
  (`quadlet/wakir-nats-kv-bucket-init.container`) to reference the
  `wakir-provisioner` image. The `Exec=`, `Volume=`, hardening, and
  network attachments stay identical — only the image and the
  outdated "pip-install at start" comment changed.
- Added a hermetic pin-form test
  (`tests/infra/test_wakir_provisioner_image_pin_form.py`) mirroring
  the SPIRE-pin invariants; added Containerfile + requirements
  invariant tests under
  `infra/spire/federation/provisioner/tests/`.
- Added a workflow_dispatch-only build workflow
  (`.github/workflows/build-wakir-provisioner.yml`) for
  Operator-Hand publishes; the existing
  `cosign-verify-images.yml` learnt a third job for the
  `wakir-provisioner` digest cross-check.

Reza-Sprint-9-Tag-4 coordination (Wirelang-import-disentanglement):

- The provisioner's `bin/nats_kv_bucket_provision.py` now probes
  `wirelang.federation.marker_stack_kv_constants` (Reza-target
  name, **assumed**) before falling back to
  `wirelang.federation.marker_stack_kv`. Same shape for
  `sequence_number_ledger_kv_constants`. If Reza picks a different
  module name, the fallback still works on the baseline tip; the
  defensive probe is a no-op at that point. Tomás-side flips the
  probe target to the actual Reza-side name in a follow-up commit
  once Reza-PR lands.
- The `wakir-provisioner` v0.1.0 image carried `cryptography`
  regardless of the Reza-side outcome: the image-gap closure
  unblocked the Pilot bring-up the same day. With Reza-PR #33
  merged, the v0.1.1 hygiene-follow-up drops the now-unused wheels
  (`cryptography`, `rfc8785`, `jsonschema`) and lands the lean
  one-wheel image (Tomás-PR §"Sprint-9 Tag-4 hygiene").

— Tomás
