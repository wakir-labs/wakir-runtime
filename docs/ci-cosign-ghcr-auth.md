# CI-Note: Cosign + GHCR Authentication for Sigstore-keyless Signing

**Status:** Live as of Phase-2 Sprint-9 Tag-5 (2026-05-13).
**Scope:** `.github/workflows/build-wakir-provisioner.yml`.
**Owner:** Tomás (dev-engineering Matrix-Lead).

---

## Why this note exists

Three consecutive workflow_dispatch runs of `build-wakir-provisioner`
(GitHub run IDs `25796754759`, `25797934843`, `25798787632`, all on
`main` 2026-05-13 11:39 / 12:04 / 12:22 UTC) failed at the
**Sigstore-keyless sign** step with:

```
Error: signing [ghcr.io/wakir-labs/wakir-provisioner@sha256:<digest>]:
signing digest:
POST https://ghcr.io/v2/wakir-labs/wakir-provisioner/blobs/uploads/:
UNAUTHORIZED: unauthenticated:
User cannot be authenticated with the token provided.
```

Build + buildah-push completed fine. The signature push to GHCR was
the failing call. Operator-Hand re-ran the workflow twice with
unchanged config; same error each time.

This note captures the diagnosis and the fix so the next person who
edits the workflow does not re-introduce the bug.

---

## Diagnosis

### Symptom

`cosign sign` mints a Sigstore-keyless certificate via the workflow's
OIDC token (the `id-token: write` permission scope), generates a
signature blob, and then **pushes that signature blob to the same
OCI registry as the image** (GHCR in our case). The push uses an OCI
v2 `POST /v2/<repo>/blobs/uploads/` request, which needs a Bearer
token with `write:packages` scope.

The workflow's `id-token: write` and `packages: write` permissions
are both correctly set in the `permissions:` block (verified pre-fix
and post-fix). So the auth was AVAILABLE; it was just not WIRED into
cosign.

### Root cause

The `Login to GHCR` step in the pre-fix workflow runs:

```yaml
- name: Login to GHCR
  if: ${{ github.event.inputs.push == 'true' }}
  run: |
    echo "${{ secrets.GITHUB_TOKEN }}" \
      | buildah login \
          --username "${{ github.actor }}" \
          --password-stdin ghcr.io
```

This authenticates the **buildah** client only. buildah maintains
its credentials in `${XDG_RUNTIME_DIR}/containers/auth.json` (or
`/run/user/<uid>/containers/auth.json`). cosign reads credentials
from `~/.docker/config.json` by default, which is the file
`docker login` writes. The two clients do not share an auth store
unless explicitly told to.

So when `cosign sign` runs:

1. ephemeral key generation OK.
2. OIDC cert retrieval OK (via `id-token: write` permission).
3. Rekor transparency log entry OK.
4. signature blob push to GHCR → no credentials → 401 UNAUTHORIZED.

This is a known cosign / GHCR interaction; the cosign docs call it
out implicitly via the `cosign login` flow but the GitHub
quickstart examples that use `docker/login-action` happen to set
the right env var as a side-effect.

### Why we didn't catch it in pre-Operator-Hand testing

The workflow is `workflow_dispatch only` and runs only when an
Operator clicks "Run workflow" with `push=true`. We had no PR-trigger
+ no dry-run-push code path that would surface the GHCR-auth gap
without actually publishing an image. Adding a `push=false` dry-run
to the build path doesn't help here — without a push there's no
sign step.

The first live Operator-Hand run (Tag-4 closeout, 2026-05-13 11:39
UTC) was the first time the sign step ever executed end-to-end. The
bug was visible only at live-bring-up time, not in the sandbox.

This is yet another instance of feedback_live_bringup_sandbox_gap.md
— hermetic tests pass, live VM does not.

---

## Fix

A separate `Cosign login to GHCR` step is inserted between
`Push to GHCR` and `Sigstore-keyless sign`. It uses the same
`secrets.GITHUB_TOKEN` and `github.actor` as the buildah login, but
writes to cosign's credential store:

```yaml
- name: Cosign login to GHCR
  if: ${{ github.event.inputs.push == 'true' }}
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: |
    set -euo pipefail
    echo "$GITHUB_TOKEN" \
      | cosign login ghcr.io \
          --username "${{ github.actor }}" \
          --password-stdin
```

This is the same `--password-stdin` posture as the buildah login
(no credential leakage to the run log).

### Alternatives considered + rejected

1. **`docker/login-action@v3`** — would work, but the workflow does
   not use docker anywhere else; pulling a heavy action just for the
   credential file write is unnecessary. `cosign login` is the
   minimal-dependency path.
2. **`COSIGN_DOCKER_MEDIA_TYPES=1` + env-based auth** — a hack that
   relies on cosign reading `DOCKER_PASSWORD` / `DOCKER_USERNAME`
   from env. Brittle, undocumented behaviour.
3. **Shared `auth.json` between buildah and cosign** — would require
   `REGISTRY_AUTH_FILE` env tweak and is fragile across cosign
   releases (cosign has been moving away from the legacy
   `containers/auth.json` path).
4. **`cosign sign --registry-username --registry-password`** —
   technically works but writes credentials into the cosign command
   line, which is then visible in the workflow log. Hard nope.

`cosign login` won on (1) minimal blast radius, (2) idiomatic
cosign posture, (3) no new action dependency, (4) credentials never
hit the log.

---

## Hermetic test coverage

Hermetic tests cannot exercise the actual GHCR auth handshake (the
sandbox does not reach GHCR per
feedback_sandbox_host_trennung.md), but we can assert the workflow's
**structure** to catch regression:

- The workflow file MUST contain a `Cosign login to GHCR` step.
- That step MUST run BEFORE `Sigstore-keyless sign`.
- That step MUST use `--password-stdin` (no inline-password leak).
- That step MUST be gated by `github.event.inputs.push == 'true'`
  (consistency with the push gate).

See `tests/ci/test_build_wakir_provisioner_workflow.py`.

---

## Operator runbook (post-fix)

When publishing a new wakir-provisioner version:

1. Resolve `requirements.txt` Operator-Hand (see provisioner
   README §3.1).
2. Open Actions → `build-wakir-provisioner` → "Run workflow".
3. Set `version_tag` (e.g. `0.1.3`).
4. Set `push` to `true`.
5. Watch run. All 11 steps should be green:
   - Checkout
   - Install crane
   - Install skopeo + jq
   - Install cosign
   - Resolve python:3.13-slim digest
   - Materialise pinned digest in Containerfile
   - Refuse build if requirements.txt is half-resolved
   - Build image with buildah
   - Login to GHCR (buildah)
   - Push to GHCR
   - **Cosign login to GHCR ← new in Sprint-9 Tag-5**
   - Sigstore-keyless sign
   - Emit workflow summary
6. Copy the pushed digest from the workflow summary into the
   bucket-init Quadlet per IMAGE_PINS.md §2.5 (or run the
   `resolve-image-pins-ci` workflow, see
   `docs/ci-image-pin-resolution.md`).

— Tomás
