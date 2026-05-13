# CI-Note: Idempotent Image-Pin Resolution

**Status:** Live as of Phase-2 Sprint-9 Tag-5 (2026-05-13).
**Scope:** `.github/workflows/resolve-image-pins-ci.yml`,
`scripts/image-pin-idempotent-resolver.sh`.
**Owner:** Tomás (dev-engineering Matrix-Lead).

---

## Why this note exists

The `infra/spire/federation/proxmox/resolve-image-pins.sh`
Operator-Hand resolver lives ON the Pilot-VM and mutates files on
that host. The repo source-of-truth pins still carry
`DIGEST_PENDING_TOMAS_REVIEW` until somebody Operator-Hand opens a
follow-up PR. Sprint-9 Tag-4 closed at this exact gap: the
wakir-provisioner image landed on GHCR + Public, but the repo's
Quadlet pin stayed on the placeholder. We had no idempotent way to
say "is the repo pin in sync with the registry?" without manual
work.

This workflow + script close that gap with an idempotent re-run
contract.

---

## What "idempotent" means here

The script must satisfy the following invariants:

1. **Re-run-stability.** A second invocation against an already-
   resolved repo state must produce ZERO file mutations and exit `0`.
2. **Cycle-stability.** Three (or N) consecutive invocations must
   converge in one step; cycles 2..N are all no-ops.
3. **Drift-detection.** If the committed pin differs from the live
   digest, the script substitutes in-place and exits `10` (sentinel,
   distinct from `1+` for real errors).
4. **Print-only-purity.** `--print-only` may detect drift but must
   not mutate any file.
5. **Half-resolved-tolerance.** A repo where some pins are
   placeholder and others are real must be a valid input; the
   script resolves the pending entries and leaves the resolved ones
   byte-identical.

The hermetic-test surface
(`tests/ci/test_image_pin_idempotent_resolver.py`) pins all five
invariants. A change to the script that breaks any one of them
breaks the test suite.

---

## How the workflow uses it

```
crane installed
   │
   ▼
./scripts/image-pin-idempotent-resolver.sh
   │
   ├── exit 0  → no drift; emit summary, do nothing
   ├── exit 10 → drift detected; create branch, commit diff, open PR
   └── exit 1+ → real error; fail the workflow
```

The exit-code-as-sentinel is the lynchpin: a "real" error must NOT
get masked as a drift, and a drift must NOT get masked as an error.
The workflow's `case "$rc" in` block enforces this branching.

---

## Comparison with the Operator-Hand VM-side resolver

| Concern                  | VM-side resolver               | CI-side resolver                      |
|--------------------------|--------------------------------|----------------------------------------|
| Where it runs            | Pilot-VM                       | GitHub-Actions runner                  |
| What it mutates          | Files on `/opt/wakir-runtime`  | Repo source files; opens a PR          |
| Digest source            | Operator passes via CLI flags  | crane fetches live (or env-stub)       |
| Idempotency posture      | Placeholder-only skip          | Full no-op-on-stable-state contract    |
| Trigger                  | Operator-Hand during bring-up  | workflow_dispatch (future: cron)       |
| Sandbox boundary         | runs ON the VM, not sandbox    | runs in GH-Actions, not sandbox        |

The two resolvers are complementary, not redundant. The VM-side
resolver is what makes the Pilot-VM start. The CI-side resolver is
what keeps the repo source-of-truth in sync with the registry.

---

## Local hermetic test

```
pytest tests/ci/test_image_pin_idempotent_resolver.py -v
```

The tests use `--digest-source env` and `FORCE_<GROUP>_DIGEST` env
vars to keep crane out of the sandbox per
`feedback_sandbox_host_trennung.md`.

---

## Operator runbook

### Routine drift check (no expected change)

1. Open Actions → `resolve-image-pins-ci` → "Run workflow".
2. Set `print_only` to `true` for a dry-run.
3. Step summary shows `drift detected: false` → done, no action.

### After publishing a new wakir-provisioner version

1. Run `build-wakir-provisioner` workflow with the new tag (see
   `docs/ci-cosign-ghcr-auth.md`).
2. Note the published digest in the build workflow's summary.
3. Open Actions → `resolve-image-pins-ci` → "Run workflow".
4. Leave `print_only` as `false`.
5. Workflow detects drift, opens an auto-PR.
6. Review the diff — confirm the new digest matches the build
   workflow's summary.
7. Merge the PR.

### When the auto-PR looks suspicious

A digest rotation on a `spire-server` or `spire-agent` "stable" tag
is a supply-chain event. If the auto-PR shows a rotation but no
upstream SPIRE release was announced:

1. Do NOT merge the PR.
2. Check the SPIRE release feed + Sigstore transparency log
   (rekor) for the new digest.
3. If the new digest is unsigned or signed by an unfamiliar
   identity, escalate to Mira and pin the previous digest manually
   while the investigation runs.

— Tomás
