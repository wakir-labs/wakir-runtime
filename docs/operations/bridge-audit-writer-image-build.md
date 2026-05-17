<!--
SPDX-License-Identifier: Apache-2.0
SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
-->

# `wakir-persona-engine-bridge-audit-writer` Image-Build

**Status:** Living operations document.
**Scope:** Build, sign and publish the
`wakir-persona-engine-bridge-audit-writer` Rust-CLI container image.
**ADR anchor:** ADR-0066 §Phase-3c Welle-3 `bridge_audit_writer`
(approved 2026-05-17). Tag-31 Mini-Welle.
**Sibling docs:**
- `docs/operations/v907-verify-image-build.md` (Tag-26 V907-verify
  image, ADR-0066 Welle-1; same build pattern).
- `docs/operations/svid-workload-identity-image-build.md` (Tag-29
  SVID-workload-identity image, ADR-0066 Welle-2; same build pattern).
- `docs/operations/cosign-policy-phase-3b.md` (the policy the image
  must satisfy at cutover time; 9-binary inventory now includes
  `bridge-audit-writer`).
- `docs/operations/quadlets-phase-3b-rust-cli.md` (the Quadlet
  installer that copies the binary onto the Pilot-VM at
  `/opt/wakir/bin/wakir-persona-engine-bridge-audit-writer`).

---

## 1. Why this image exists

ADR-0066 (approved 2026-05-17) accelerates Phase-3c to 4 weeks
(Option A+). Each Welle ships a single low-blast-radius backend
flip from the Python production-default to a compiled Rust-CLI
subprocess-bridge:

- **Welle-1 (Tag-19/26):** `v907-verify` — pin-hash recompute path.
- **Welle-2 (Tag-25/29):** `svid-workload-identity` — SPIFFE
  Workload-API socket-presence probe path.
- **Welle-3 (Tag-31, this image):** `bridge_audit_writer` — the
  Doppelbetrieb-Shadow `EngineeringOutputEvent` envelope writer.

The writer is the **emit-half** of the Doppelbetrieb-Shadow audit
substrate; the replay-half lives in PR #131
(`persona-engine-bridge-diff`) and PR #147
(`persona-engine-bridge-audit-replay`) and shipped earlier in
Phase-3a. Tag-31 closes the cross-language Python↔Rust round-trip:
the Rust writer emits a JCS-canonical envelope byte-identical to the
Python `wirelang.persona_engine.bridge_audit_writer.
EngineeringOutputEvent.to_jcs_bytes()` output, and the replay engine
consumes both indistinguishably.

---

## 2. Subcommand surface

The binary lives at `/usr/local/bin/wakir-persona-engine-bridge-audit-writer`
inside the image (and at `/opt/wakir/bin/wakir-persona-engine-bridge-audit-writer`
on the Pilot-VM host after the Quadlet installer runs). Three
subcommands:

```text
usage:
    wakir-persona-engine-bridge-audit-writer emit \
        --org-id ORG --persona-id PERSONA --session-id SID \
        --step-index N --output-kind KIND \
        --engine-version VER --v907-pin sha256:<64hex> \
        [--ts-utc RFC3339] \
        [--payload-file PATH | --payload-stdin]
    wakir-persona-engine-bridge-audit-writer info
    wakir-persona-engine-bridge-audit-writer --version
    wakir-persona-engine-bridge-audit-writer --help
```

### 2.1 `emit`

Reads payload bytes from `--payload-file PATH` (when given) or from
stdin (default), hashes them with SHA-256, builds an
`EngineeringOutputEvent` envelope from the supplied flags, and
prints the envelope as a single JCS-canonical JSON line on stdout.

The payload bytes themselves are **never** written to stdout — only
their hash lands in the envelope's `output_payload_sha256` field.
This mirrors the Python writer's hash-only posture in
`bridge_audit_writer.BridgeAuditWriter.emit`.

Exit codes:
- `0` — envelope emitted successfully
- `1` — internal error (I/O failure on payload read, JCS error)
- `2` — `--payload-file PATH` not found
- `64` — usage error (unknown subcommand, missing required flag,
  malformed argument shape, bad `--output-kind`, bad `--v907-pin`
  shape)

Substrate fences:
- `--output-kind` must be one of `tool_call` | `reply` |
  `audit_annotation` (closed set, mirrors the Python writer's
  `ValueError` guard).
- `--v907-pin` must be `sha256:<64-lowercase-hex>` (mirrors the
  pin-string discipline from `wirelang.persona_engine.bridge_audit_writer`).

### 2.2 `info`

Prints one `key=value` pair per line of operator-discoverable
metadata:

- `engineering_output_schema=wakir.persona.engineering-output/1`
- `default_preframework_sink_template=/var/lib/wakir/persona/{persona_id}/bridge-audit.md`
- `python_authority=wirelang.persona_engine.bridge_audit_writer`
- `library_crate=persona-engine-bridge-audit-replay`
- `version=<CARGO_PKG_VERSION>`

Always exits 0. Parity with the `wakir-persona-engine-svid-workload-identity info`
surface so a future shared operator script can consume both.

---

## 3. Cross-language byte-parity contract

The Rust emit envelope is byte-identical to the Python pendant's
`EngineeringOutputEvent.to_jcs_bytes()` output for the same input.
Verification recipe (host-side, requires Python + the workspace):

```sh
# Rust side:
echo -n "hello-world" | \
    /opt/wakir/bin/wakir-persona-engine-bridge-audit-writer emit \
        --org-id acme --persona-id tomas --session-id sess-1 \
        --step-index 0 --output-kind reply \
        --engine-version 0.2.0-pilot \
        --v907-pin sha256:$(printf 'a%.0s' {1..64}) \
        --ts-utc 2026-05-17T12:34:56Z \
        --payload-stdin

# Python side (must produce byte-identical output):
python3 -c "
from wirelang.persona_engine.bridge_audit_writer import \
    EngineeringOutputEvent, sha256_hex
evt = EngineeringOutputEvent(
    org_id='acme', persona_id='tomas', session_id='sess-1',
    step_index=0, output_kind='reply',
    output_payload_sha256=sha256_hex(b'hello-world'),
    engine_version='0.2.0-pilot', v907_pin='sha256:' + 'a'*64,
    ts_utc='2026-05-17T12:34:56Z',
)
print(evt.to_jcs_bytes().decode('utf-8'))
"
```

Both invocations produce:

```json
{"engine_version":"0.2.0-pilot","event_kind":"engineering_output","org_id":"acme","output_kind":"reply","output_payload_sha256":"sha256:afa27b44d43b02a9fea41d13cedc2e4016cfcf87c5dbf990e593669aa8ce286d","persona_id":"tomas","schema":"wakir.persona.engineering-output/1","session_id":"sess-1","step_index":0,"ts_utc":"2026-05-17T12:34:56Z","v907_pin":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

The lexicographically-sorted keys and the absence of whitespace are
the RFC 8785 JCS canonical-form requirement; the Rust side uses
`serde_jcs` and the Python side uses
`json.dumps(..., sort_keys=True, separators=(',',':'))` — both
implementations agree byte-for-byte on this input shape (the F1 /
F2 / F3 fixtures in
`wirelang-rust/crates/persona-engine-bridge-audit-replay/tests/`
pin the same property under stream-level diff).

---

## 4. Build workflow

Workflow file: `.github/workflows/build-rust-cli-bridge-audit-writer.yml`.

Hybrid trigger surface:

1. **`push` to `main`** when paths under
   `wirelang-rust/crates/persona-engine-bridge-audit-replay/**`,
   `infra/bridge-audit-writer-rust-cli/Containerfile` or the
   workflow file itself change — runs `cargo build --release` +
   `buildah bud` in **dry-run** mode (no GHCR push, no Cosign sign).
   This is the substrate-CI lane: it catches build regressions
   early without publishing an image.

2. **`workflow_dispatch`** with `inputs.push='true'` — the
   authorised-maintainer flow that actually publishes to GHCR and
   Sigstore-keyless-signs the resulting digest against the
   GitHub-Actions OIDC identity of
   `wakir-labs/wakir-runtime/.github/workflows/build-rust-cli-bridge-audit-writer.yml`.

Substrate fences enforced at workflow time:

- `version_tag` matches `^[0-9]+\.[0-9]+\.[0-9]+-pilot$` on
  workflow_dispatch (Sprint-Pengine-13 pattern).
- Base-layer digests resolved via skopeo **and** crane; refuses to
  proceed if the two disagree.
- `DIGEST_PENDING_KAI_REVIEW` placeholders in the Containerfile must
  be fully substituted before buildah runs.
- The Push to GHCR step is conditional on `inputs.push == 'true'`;
  the Cosign sign step is conditional on the same flag. No echter
  Image-Push from the substrate-CI lane.

Permission posture: least-privilege (`contents:read`,
`packages:write`, `id-token:write` only).

---

## 5. Operator-Hand publish recipe

The publish path is Operator-Hand only (the same workflow_dispatch
guarded by an explicit `push=true` opt-in as the V907-verify and
SVID-workload-identity images).

```sh
gh workflow run build-rust-cli-bridge-audit-writer \
    --ref main \
    -f version_tag=0.1.0-pilot \
    -f push=true
```

After the run completes:

```sh
# Pull the digest artefact:
gh run download <run-id> -n wakir-persona-engine-bridge-audit-writer-digest
cat wakir-persona-engine-bridge-audit-writer.digest
# → sha256:<64hex>
# → <64hex>

# Verify the Sigstore-keyless signature:
DIGEST=$(head -n1 wakir-persona-engine-bridge-audit-writer.digest)
cosign verify \
    --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
    --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
    ghcr.io/wakir-labs/wakir-persona-engine-bridge-audit-writer:0.1.0-pilot@${DIGEST}
```

---

## 6. Welle-3 cutover step

Once the image is published and Sigstore-verified:

1. Resolve the pinned digest into the carrier Quadlet
   (`quadlet/wakir-persona-engine-bridge-audit-writer.container` —
   not yet committed; cutover-step adds it) and into the
   Cosign-Policy YAML's `expected_image_digest` slot via
   `scripts/image-pin-idempotent-resolver.sh`.
2. Land a coordinated PR that flips
   `WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=rust` in the persona-engine
   Quadlet drop-in.
3. Operator-Hand `systemctl restart wakir-persona-engine.service`
   on the Pilot-VM; verify via `podman logs` that the
   `backend_decision: rust` audit-record lands without a
   `fallback_reason: missing_binary` line.

The cutover step is **separate** from this image-build PR.

---

## 7. Sandbox boundary

This workflow runs on GitHub-Actions runners, which are host-of-
record (not the claude-dev sandbox). The dry-run path is reachable
from the substrate-CI lane (push-to-main builds); the push path is
workflow_dispatch only per `feedback_sandbox_host_trennung.md`.

The hermetic test surface
(`tests/workflows/test_build_rust_cli_bridge_audit_writer.py`,
`tests/infra/test_cosign_policy_phase_3b.py`) validates the
workflow STRUCTURE on disk — no cosign / crane / skopeo
invocations against `ghcr.io` from the sandbox.

---

## 8. Cross-references

- ADR-0066 §Phase-3c Welle-3 `bridge_audit_writer` (approved
  2026-05-17).
- ADR-0065 §Welle-3 listing (precondition closure via PR #131
  bridge-diff + PR #147 bridge-audit-replay + this Tag-31 image-build).
- ADR-0060 — Cosign-Policy on Pilot-Container-Images.
- ADR-0035 §C-Drift-Closure — the ADR this cutover will close for
  the bridge_audit_writer module.
- PR #131 (`persona-engine-bridge-diff`) — JCS / hash primitive
  reused via the lib crate's `AuditRecord::jcs_hash()`.
- PR #147 (`persona-engine-bridge-audit-replay`) — the library
  crate this binary lives in; the `AuditRecord::to_envelope()` wire
  shape is the single-source-of-truth.
- PR #194 (Tag-26 V907-verify image-build) — sibling Welle-1 image.
- PR #201 (Tag-29 SVID-workload-identity image-build) — sibling
  Welle-2 image.

— Kai
