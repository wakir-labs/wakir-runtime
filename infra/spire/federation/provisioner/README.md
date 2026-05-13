# wakir-provisioner image

**Image:** `ghcr.io/wakir-labs/wakir-provisioner`
**Source:** [`infra/spire/federation/provisioner/Containerfile`][cf]
**License:** Apache-2.0 (wheel licences shipped inside the image; see
`pip show <pkg>` for per-wheel attribution)
**Sprint context:** Phase-2 Sprint-9 Tag-4 — Bug-Fix-Welle for the
Pilot-VM bring-up regression (Mira-Bug-Bilanz 2026-05-13, Bug 6).

[cf]: ./Containerfile

## Scope

Minimal Python image carrying the four wheels the per-org NATS-KV
bucket provisioner (`bin/nats-kv-bucket-provision`, Sprint-9 Tag-1)
needs at runtime:

- `nats-py` (NATS-JetStream client)
- `cryptography` (transitive via `wirelang.identity` until the
  Reza-side Sprint-9 Tag-4 disentanglement lands)
- `rfc8785` (JCS canonical JSON)
- `jsonschema` (Wirelang Layer-0/1/2 conformance)

The image deliberately does NOT carry the `wakir-runtime` tree
itself. The runtime is bind-mounted into the container from the host
at `/opt/wakir-runtime` (see Quadlet `Volume=` lines). Bumping the
Wirelang/runtime tree does not require an image rebuild; bumping
any of the four wheel pins above does.

## Why a dedicated image (and not `python:3.13-slim` plus pip-install)

The Sprint-9 Tag-1 Quadlet was authored against
`docker.io/library/python:3.13-slim` on the (incorrect) assumption
that the slim image ships `nats-py` pre-installed. The Sprint-9
Tag-4 live-bring-up on the Pilot-VM crashed at unit-start with
`ModuleNotFoundError: cryptography` because the provisioner's
transitive imports through `wirelang.federation.marker_stack_kv`
pull in `wirelang.identity` which requires `cryptography`. `nats-py`
itself was also absent on slim — independent of the
`cryptography` issue.

Three resolution options were on the table:

| Option | What it does | Trade-offs |
|---|---|---|
| **A** Dedicated image (this) | Wheels baked at image build time, hash-pinned, digest-pinned at Quadlet pull time | One supply-chain artifact to provenance; cold-start = single image pull |
| **B** `ExecStartPre` pip-install | Wheels installed to tmpfs at unit start | Re-introduces a supply-chain network egress on every unit start, breaks `ReadOnly` posture, fails under air-gap |
| **C** Wirelang-side disentanglement | Refactor `marker_stack_kv` to import its substrate-shaping constants without triggering `wirelang.identity` | Owned by Reza; tidies the codebase but doesn't ship `nats-py` — A is still needed |

Mira-recommendation (Bug 6, Bug-Bilanz 2026-05-13) was A + C. This
README + Containerfile is the A track; the C track is Reza's
Sprint-9 Tag-4 Wirelang-import-disentanglement work.

## Build + publish recipe (Operator-Hand)

The sandbox does not push container images per
[`feedback_sandbox_host_trennung.md`][sandbox-trennung]. The
recipe below runs on a build host (GitHub-Actions runner or an
Operator-Hand workstation with `podman` / `buildah` + `cosign`).

[sandbox-trennung]: ../../../../.claude/feedback_sandbox_host_trennung.md

### 1. Resolve PyPI hashes (one-time per pin bump)

```sh
# For each pinned wheel in provisioner/requirements.txt, fetch the
# canonical sha256 from the PyPI JSON API and substitute the
# HASH_PENDING_TOMAS_REVIEW placeholder. Example for nats-py:
curl -fsS https://pypi.org/pypi/nats-py/2.14.0/json \
    | jq -r '.urls[] | "--hash=sha256:" + .digests.sha256'

# Substitute the placeholder lines in provisioner/requirements.txt
# with the resolved --hash= lines (one per artifact).
```

A hermetic test
(`provisioner/tests/test_requirements_hash_form.py`) enforces that
every line either carries the placeholder token OR a canonical
64-hex sha256. Half-resolved state is flagged as an invariant
breach.

### 2. Resolve the base-image digest

```sh
# Resolve docker.io/library/python:3.13-slim digest via the same
# DockerHub recipe documented in infra/spire/federation/IMAGE_PINS.md
# §2.4. Substitute DIGEST_PENDING_TOMAS_REVIEW in the FROM line.
PYTHON_DIGEST=$(skopeo inspect docker://python:3.13-slim | jq -r '.Digest')
sed -i "s|python:3.13-slim@sha256:DIGEST_PENDING_TOMAS_REVIEW|python:3.13-slim@${PYTHON_DIGEST}|" \
    infra/spire/federation/provisioner/Containerfile
```

### 3. Build the image

```sh
# Build (rootless podman recommended):
podman build \
    --tag ghcr.io/wakir-labs/wakir-provisioner:0.1.0 \
    --label "org.opencontainers.image.revision=$(git rev-parse HEAD)" \
    --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    -f infra/spire/federation/provisioner/Containerfile \
    infra/spire/federation/provisioner/
```

### 4. Sign + push (Sigstore keyless)

```sh
# Login (uses a fine-grained GHCR token):
echo "$GHCR_TOKEN" | podman login ghcr.io -u "$GHCR_USER" --password-stdin

# Push:
podman push ghcr.io/wakir-labs/wakir-provisioner:0.1.0

# Resolve the pushed digest:
PROVISIONER_DIGEST=$(podman image inspect \
    ghcr.io/wakir-labs/wakir-provisioner:0.1.0 \
    --format '{{ index .RepoDigests 0 }}' | sed 's|.*@||')

# Sigstore keyless sign (OIDC against the GitHub Actions identity if
# you're driving this from the workflow, or an authenticated dev
# identity Operator-Hand):
cosign sign \
    "ghcr.io/wakir-labs/wakir-provisioner@${PROVISIONER_DIGEST}"
```

### 5. Pin the digest in the Quadlet

```sh
sed -i "s|wakir-provisioner:0.1.0@sha256:DIGEST_PENDING_TOMAS_REVIEW|wakir-provisioner:0.1.0@${PROVISIONER_DIGEST}|" \
    quadlet/wakir-nats-kv-bucket-init.container

# Re-run the hermetic pin-form test:
pytest tests/infra/test_wakir_provisioner_image_pin_form.py
```

### 6. Commit + open PR

```sh
git add infra/spire/federation/provisioner quadlet \
    infra/spire/federation/IMAGE_PINS.md
git commit -m "chore(provisioner): pin wakir-provisioner:0.1.0 to verified digest"
```

## Verification (hermetic, sandbox-safe)

The sandbox-side hermetic tests cover:

- `tests/infra/test_wakir_provisioner_image_pin_form.py` — Quadlet
  pin syntax (placeholder OR 64-hex digest, canonical form).
- `infra/spire/federation/provisioner/tests/test_containerfile.py`
  — Containerfile invariants (FROM-line digest pin, requirements
  copy + hash-pinned install, non-root user, OCI labels).
- `infra/spire/federation/provisioner/tests/test_requirements_hash_form.py`
  — requirements.txt pin syntax (placeholder OR 64-hex sha256).

No sandbox process pulls, builds, or pushes the image. Live build
+ publish is Operator-Hand per `feedback_sandbox_host_trennung.md`.

## Drift alarm

An unannounced re-push of a Docker Official Image is a community-
relevant supply-chain event; if the base-image digest changes
upstream, halt the build and Zone-C cross-review the upstream
announcement (Docker Library GitHub release notes + Python release
notes). Same posture as `infra/spire/federation/IMAGE_PINS.md` §2.4
for direct `python:3.13-slim` consumers.

— Tomás
