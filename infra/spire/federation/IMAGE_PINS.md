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

Both images MUST stay version-parity: SPIRE upstream releases the
server and agent as a paired binary set, and version-skew between the
two has been observed to break federation-bundle handshake in prior
upstream releases.

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
against `ghcr.io` per `feedback_sandbox_host_trennung.md`. The
hermetic test surface validates the placeholder/digest SYNTAX only —
the live verification is Operator-Hand on a host that has GHCR
network access and the `cosign` CLI installed.

— Kai
