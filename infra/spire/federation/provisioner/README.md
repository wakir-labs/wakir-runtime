# wakir-provisioner image

**Image:** `ghcr.io/wakir-labs/wakir-provisioner`
**Source:** [`infra/spire/federation/provisioner/Containerfile`][cf]
**License:** Business Source License 1.1 (`BUSL-1.1`); see
[`LICENSE-BSL.md`](./LICENSE-BSL.md). Change Date: 2030-05-13.
Change License: Apache-2.0. Per-wheel licences inside the image
(`nats-py` — Apache-2.0; CPython stdlib — PSF-2.0; transitive
dependencies — BSD/Apache-2.0) ship in the wheels themselves and
are reachable via `pip show <pkg>`; the BSL header does not extend
to those transitive wheels.
**Sprint context:** Phase-2 Sprint-9 Tag-4 — Bug-Fix-Welle for the
Pilot-VM bring-up regression (Mira-Bug-Bilanz 2026-05-13, Bug 6).
**Relicense context:** AR-Decision 2026-05-13 ~14:00 CEST —
Apache-2.0 → BSL 1.1, consistent with the WAT-Pipeline-Server
Phase-1a BSL pattern (ADR-0034 federation-server-substrate-
sequence).

[cf]: ./Containerfile

## Scope

Minimal Python image carrying the runtime wheel the per-org NATS-KV
bucket provisioner (`bin/nats-kv-bucket-provision`, Sprint-9 Tag-1)
needs at runtime:

- `nats-py` (NATS-JetStream client)

### Version history

- **v0.1.0** — initial image, four wheels (`nats-py`,
  `cryptography`, `rfc8785`, `jsonschema`) to satisfy the
  provisioner's transitive imports through `wirelang.identity`.
  Apache-2.0.
- **v0.1.1** — post Reza-PR #33 (Wirelang-Import-Disentanglement,
  PEP-562 lazy `__getattr__` on `wirelang.federation`); wheel set
  shrunk to `nats-py` only. Apache-2.0.
- **v0.1.2** — BSL 1.1 relicense (AR-Decision 2026-05-13). No
  functional change vs. v0.1.1; image-level licence label flipped
  from `Apache-2.0` to `BUSL-1.1`, Change Date 2030-05-13,
  Change License Apache-2.0. Consistent with the WAT-Pipeline-
  Server Phase-1a BSL pattern (ADR-0034).

### Wheel-set shrink (v0.1.1, post Reza-PR #33)

The v0.1.0 image carried four wheels (`nats-py`, `cryptography`,
`rfc8785`, `jsonschema`) to satisfy the provisioner's transitive
imports through `wirelang.identity`. After Reza-PR #33
(Wirelang-Import-Disentanglement, PEP-562 lazy `__getattr__` on
`wirelang.federation`), the transitive identity-stack import chain
no longer fires for the marker-stack-kv / sequence-number-ledger
code paths the provisioner exercises. The v0.1.1 image drops the
three now-unused wheels.

The image deliberately does NOT carry the `wakir-runtime` tree
itself. The runtime is bind-mounted into the container from the host
at `/opt/wakir-runtime` (see Quadlet `Volume=` lines). Bumping the
Wirelang/runtime tree does not require an image rebuild; bumping
the `nats-py` wheel pin above does.

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
    --tag ghcr.io/wakir-labs/wakir-provisioner:0.1.2 \
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
podman push ghcr.io/wakir-labs/wakir-provisioner:0.1.2

# Resolve the pushed digest:
PROVISIONER_DIGEST=$(podman image inspect \
    ghcr.io/wakir-labs/wakir-provisioner:0.1.2 \
    --format '{{ index .RepoDigests 0 }}' | sed 's|.*@||')

# Sigstore keyless sign (OIDC against the GitHub Actions identity if
# you're driving this from the workflow, or an authenticated dev
# identity Operator-Hand):
cosign sign \
    "ghcr.io/wakir-labs/wakir-provisioner@${PROVISIONER_DIGEST}"
```

### 5. Pin the digest in the Quadlet

```sh
sed -i "s|wakir-provisioner:0.1.2@sha256:DIGEST_PENDING_TOMAS_REVIEW|wakir-provisioner:0.1.2@${PROVISIONER_DIGEST}|" \
    quadlet/wakir-nats-kv-bucket-init.container

# Re-run the hermetic pin-form test:
pytest tests/infra/test_wakir_provisioner_image_pin_form.py
```

### 6. Commit + open PR

```sh
git add infra/spire/federation/provisioner quadlet \
    infra/spire/federation/IMAGE_PINS.md
git commit -m "chore(provisioner): pin wakir-provisioner:0.1.2 to verified digest"
```

## Caller contract (no baked ENTRYPOINT, no baked CMD)

**Sprint-9 Tag-6 change.** The image is strictly caller-driven: it
ships **no** `ENTRYPOINT` and **no** `CMD`. The caller (the
bucket-init Quadlet, or any future operator-side `podman run`
invocation) MUST supply the full command line including the Python
interpreter.

Canonical Quadlet invocation:

```ini
Exec=python3 /opt/wakir/bin/nats-kv-bucket-provision \
  --servers nats://wakir-nats:4222 \
  --orgs-file /etc/wakir/onboarded-orgs
```

Canonical operator smoke (Operator-Hand, build host or live VM):

```sh
podman run --rm ghcr.io/wakir-labs/wakir-provisioner:<tag>@sha256:<digest> \
    python3 --version
```

**Why this convention.** The v0.1.1 image baked
`ENTRYPOINT ["python3"]` plus `CMD ["--version"]`. The bucket-init
Quadlet supplied its own `Exec=python3 /opt/wakir/bin/...` line; the
result was the entrypoint+exec concatenation
`python3 python3 /opt/wakir/bin/...` where the second `python3` was
interpreted as a script path relative to
`WORKDIR=/opt/wakir-runtime`. The container crashed at unit start
with `python3: can't open file '/opt/wakir-runtime/python3'`
(Live-Bring-up-2-Bilanz 2026-05-14, Bug 6).

Two fix paths were on the table — drop the entrypoint, or remove
`python3` from the Quadlet `Exec=`. Both work, but they only work
when chosen consistently. The Sprint-9 Tag-6 resolution applies BOTH
as defence-in-depth:

1. The Quadlet keeps `Exec=python3 /opt/wakir/bin/...` (Kai's Tag-6
   edit; the Quadlet stays the canonical caller and is explicit
   about which interpreter it wants).
2. The image drops `ENTRYPOINT` and `CMD` entirely (Tomás-side; the
   image cannot silently re-introduce the doubled-`python3` bug for
   any future caller).

A hermetic test
(`infra/spire/federation/provisioner/tests/test_containerfile.py`)
enforces the caller-driven convention: the Containerfile MUST NOT
contain an active `ENTRYPOINT` or `CMD` directive.

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

## License (BSL 1.1)

This module — the `infra/spire/federation/provisioner/` directory
and the published image `ghcr.io/wakir-labs/wakir-provisioner`,
together with the sandbox-side per-org NATS-KV bucket provisioner
driver `bin/nats_kv_bucket_provision.py` — is licensed under the
Business Source License 1.1 with automatic four-year conversion to
Apache 2.0. The canonical header lives in
[`LICENSE-BSL.md`](./LICENSE-BSL.md).

Summary of the licensing terms:

| Use case | Allowed under BSL 1.1? |
|---|---|
| Self-hosting against your own organisation's SPIRE-Federation substrate | Yes |
| Self-hosting for subsidiaries or contractors operating on your behalf | Yes |
| Commercial multi-tenant federation-as-a-service competing with Wakir Cloud | No — separate Wakir-Cloud licence required |
| Re-using individual wheel artefacts (`nats-py` etc.) shipped inside the image | Yes, under the wheel's own upstream licence (Apache-2.0, BSD, PSF-2.0) — the BSL header on the image does not extend to those wheels |
| Building from source for evaluation, testing, CI, audit | Yes |

**Change Date:** 2030-05-13 (four years after the first BSL-licensed
image publication, `wakir-provisioner:0.1.2`).
**Change License:** Apache License, Version 2.0.

The conversion is a contractual commitment of the Licensor, not a
unilateral promise: once an image release is published under the
BSL header, that specific release automatically converts to
Apache-2.0 on the stated Change Date.

The `wat/` module of this repository carries a sibling BSL header
with its own independent Change Date — see
[`wat/LICENSE-BSL.md`](../../../../wat/LICENSE-BSL.md). All other
directories of this repository follow the repository-root
[LICENSE](../../../../LICENSE) (Apache-2.0 by default; CC BY 4.0
for documentation where indicated).

## Drift alarm

An unannounced re-push of a Docker Official Image is a community-
relevant supply-chain event; if the base-image digest changes
upstream, halt the build and Zone-C cross-review the upstream
announcement (Docker Library GitHub release notes + Python release
notes). Same posture as `infra/spire/federation/IMAGE_PINS.md` §2.4
for direct `python:3.13-slim` consumers.

— Tomás
