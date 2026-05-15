# Resolver Trust-Modes — Image-Pin Verification Selector

<!--
SPDX-License-Identifier: BUSL-1.1
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

Phase-2 Sprint-Tag-8 — `WAKIR_RESOLVER_TRUST_MODE` documentation.
Companion to `infra/spire/federation/wakir-pilot-bootstrap.sh` step-5
(image-pin resolve) and to `scripts/image-pin-idempotent-resolver.sh`
(CI-side resolver).

## Why this exists

Sprint-10 Tag-7 Bug-36 collapsed the bootstrap's skip-cosign-verify
branch into a path that resolves all four image pins via skopeo only.
The fix unblocked the Live-VM run on `wakir-orbit` 2026-05-15 ~20:10
CEST, but it also broadened the trust-base for the SPIRE-server,
SPIRE-agent, and python-base pins: they are now resolved from
repository-served manifests without Sigstore signature verification.

For the Pilot-Phase this is acceptable. The Operator-Hand-runbook
still inspects each digest before commit, and the
`image-pin-idempotent-resolver.sh` CI cron job catches upstream
re-push drift within hours.

For Production this is not acceptable. ADR-0023 (image-pin contract)
requires Sigstore-keyless verification on the `ghcr.io/spiffe/*` and
`ghcr.io/wakir-labs/*` images. The Pilot-Phase skip path was a
temporary unblocker, not a target steady state.

`WAKIR_RESOLVER_TRUST_MODE` makes the trust-base explicit so the
Pilot-Phase tolerance and the Production requirement live side-by-
side in the same script and are selected by env-var, not by silent
implicit defaults.

## Modes

### `cosign-strict` (Default — Production)

Requires Sigstore-keyless verification for `ghcr.io/spiffe/*` and
`ghcr.io/wakir-labs/*` images. Skopeo cross-check verifies digest
agreement (cosign-resolved digest must equal skopeo-resolved digest;
mismatch is a Zone-C halt with cross-review trigger).

`docker.io/library/python:3.13-slim` is skopeo-only by upstream
policy — DockerHub does not sign its library images.

**Failure modes:**

- Any cosign-verify failure on a signed image aborts step-5 with
  rc=2.
- Cosign/skopeo digest disagreement aborts step-5 with rc=2 and
  triggers a Zone-C cross-review banner.

**When to use:** Production rollouts, Phase-3 cutover and beyond.

### `skopeo-only-all-4` (Pilot-Phase — DEV)

Resolves all four image pins via skopeo only. No Sigstore signature
verification on any image.

Equivalent to the Sprint-10 Tag-7 Bug-36-Fix path. This is the
canonical spelling for the Bug-36-Fix behaviour; the legacy spelling
`WAKIR_SKIP_COSIGN_VERIFY=1` maps to this mode.

**Trust-base:** repository TLS + repository manifest integrity. No
Sigstore signing chain.

**Failure modes:**

- Skopeo-inspect failure on `spire-server`, `spire-agent`, or
  `python` aborts step-5 with rc=2.
- Skopeo-inspect failure on `wakir-provisioner` is non-fatal
  (first-bring-up may pre-date image publish); placeholder is
  retained.

**When to use:** Pilot-Phase Operator-Hand bring-ups, ADR-0058
Migrations-Pilot, Live-VM-Acceptance lane. Documented departure
from the production trust-base; recorded in the bring-up bilanz.

### `mixed` (Hybrid — Sigstore-Outage Fallback)

Cosign-verify where signing is available (`ghcr.io/spiffe/*`,
`ghcr.io/wakir-labs/*`), skopeo-fallback only for the SPIRE
allowlist when the Sigstore signature is temporarily unavailable
(e.g. Sigstore-outage during a bring-up window).

`python:3.13-slim` stays skopeo-only.

The fallback allowlist is hard-coded in the bootstrap; Operator-Hand
cannot widen it without a source-patch and a Zone-C cross-review.

**Trust-base:** mixed — Sigstore where reachable, repository trust
for explicit allowlist when not.

**When to use:** Sigstore-outage windows where Production cutover is
mid-flight and reverting to `cosign-strict` would block the rollout.
The mode produces an explicit log-banner so the bring-up bilanz
records which images fell back to skopeo.

## Back-compat with `WAKIR_SKIP_COSIGN_VERIFY`

The legacy env-var `WAKIR_SKIP_COSIGN_VERIFY=1` is preserved as an
alias for `WAKIR_RESOLVER_TRUST_MODE=skopeo-only-all-4`.

| `WAKIR_RESOLVER_TRUST_MODE` | `WAKIR_SKIP_COSIGN_VERIFY` | Effective mode |
|-----------------------------|----------------------------|----------------|
| unset                       | unset/`0`                  | `cosign-strict` |
| unset                       | `1`                        | `skopeo-only-all-4` |
| `cosign-strict`             | unset/`0`                  | `cosign-strict` |
| `cosign-strict`             | `1`                        | **ERROR**: conflict |
| `skopeo-only-all-4`         | any                        | `skopeo-only-all-4` (back-compat alias set internally) |
| `mixed`                     | any (must not be `1`)      | `mixed` |

Setting `WAKIR_RESOLVER_TRUST_MODE=cosign-strict` together with
`WAKIR_SKIP_COSIGN_VERIFY=1` is a hard error — the two are
mutually exclusive and the bootstrap refuses to start rather than
silently choosing one over the other.

## Production-migration plan

Phase-3 cutover (ADR-0058 §"Phase 4 Cutover-Entscheidung") makes
`cosign-strict` mandatory:

1. **Pre-cutover audit:** all Live-VM bring-ups since Pilot-Phase
   start are reviewed for which trust-mode they used. Any
   `skopeo-only-all-4` bring-up that landed in the cutover image-
   set is re-bringup'ed under `cosign-strict` and the resulting
   digest is compared byte-for-byte.

2. **Cutover gate:** `cosign-strict` is the only accepted mode on
   the Pilot-VM. The cutover ADR makes `skopeo-only-all-4` a
   one-way ticket back to DEV; production hosts that ever ran
   skopeo-only are reinstalled from clean.

3. **CI enforcement:** The `image-pin-idempotent-resolver.sh` CI
   workflow runs `cosign verify` post-Cutover. A drift detected
   without a corresponding Sigstore signature triggers a Zone-C
   cross-review, not a silent re-pin.

## Threat-model summary

| Threat                                       | `cosign-strict` | `skopeo-only-all-4` | `mixed`           |
|----------------------------------------------|-----------------|---------------------|-------------------|
| Upstream registry compromise                 | **detected**    | undetected          | detected for signed images |
| Upstream registry MITM (TLS-strip)           | **detected**    | undetected          | detected for signed images |
| Upstream maintainer-key compromise           | **detected**    | undetected          | detected for signed images |
| Upstream image re-push (drift)               | detected by resolver idempotency | detected by resolver idempotency | detected by resolver idempotency |
| Sigstore-side outage during bring-up         | bring-up blocks | unaffected          | logged + skopeo-fallback |
| Bug-36-class skopeo-only-leak                | **caught**      | n/a (mode is by-design) | logged on signed-fallback |

`detected` means the bootstrap halts with rc=2 and a Zone-C banner.
`undetected` means the bring-up proceeds with a tampered image.

## See also

- ADR-0023 — Image-pin contract.
- ADR-0058 — Pilot-Persona-Migrations-Plan §"Phase 4 Cutover".
- `infra/spire/federation/IMAGE_PINS.md` — per-image trust-source
  documentation (Sigstore-keyless identity, OIDC issuer, etc).
- `scripts/image-pin-idempotent-resolver.sh` — CI-side resolver
  (idempotent, exit-code-disciplined).
- `infra/spire/federation/proxmox/resolve-image-pins.sh` —
  Operator-Hand VM-side resolver.

-- Kai
