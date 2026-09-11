<!--
SPDX-License-Identifier: Apache-2.0
Copyright (c) 2026 Callandor GmbH and contributors
-->

# Secret-Scan Report — 2026-09 (ADR-0072 Phase 4, Sub-Item 4f)

**Scope:** one-off full-history scan of the three public wakir repositories,
plus activation of the `secret-scan` CI gate in each of them.
**Date:** 2026-09-11
**Tool:** gitleaks v8.30.1 (release binary `gitleaks_8.30.1_linux_x64.tar.gz`,
SHA-256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`,
verified against `gitleaks_8.30.1_checksums.txt`; release URLs HTTP-200
verified 2026-09-11).
**Command (history):** `gitleaks git --log-opts="--all" .` on full clones with
all remote refs fetched — first pass with the built-in default rules only,
second pass with the repo-local `.gitleaks.toml`.
**Command (current tree):** `gitleaks dir .`

This document contains **counts and classifications only**. No finding
content, no matched strings, no secret values. This is deliberate
(operating assumption from the external review §13: anything committed
publicly is cloned and indexed immediately).

## 1. Results

### 1.1 Default rules, no allowlist (baseline)

| Repo | Commit range (root → tip) | Commits scanned | History findings | Current-tree findings |
|---|---|---|---|---|
| wakir-runtime | `3f9fc4d` → `8465c49` | 661 | 156 | 100 |
| wakir-protocol | `18fe82d` → `b7de631` | 5 | 15 | 15 |
| wakir-verify | `c19ad26` → `706d3e3` | 4 | 0 | 0 |

History findings by rule:

| Repo | `generic-api-key` | `private-key` | other rules |
|---|---|---|---|
| wakir-runtime | 155 | 1 | 0 |
| wakir-protocol | 15 | 0 | 0 |
| wakir-verify | 0 | 0 | 0 |

### 1.2 Classification (every finding reviewed individually)

| Class | runtime | protocol | verify | Assessment |
|---|---|---|---|---|
| SHA-256 digest field named `*_token_hash` in WAT manifests / proof-path vectors (test fixtures) | 141 | 7 | 0 | **false-positive** — a digest of a token, not a token; keyword match only |
| `public_keys[].key_hex` in AIP identity-document test vectors and one replay fixture | 7 | 6 | 0 | **test-only, public material** — Ed25519 / compressed-secp256k1 *public* keys (32/33 bytes) |
| Function names in the identity-substrate registry (`("key_derivation", "derive_sub_key_…")`) | 2 | 2 | 0 | **false-positive** — identifiers, not key material |
| Synthetic `approval_token=` literal in one test module | 4 | 0 | 0 | **test-only** — dummy value for receipt rendering |
| PEM marker `BEGIN PRIVATE KEY` quoted in a test-module docstring | 1 | 0 | 0 | **false-positive** — describes the accepted envelope; keys are generated at test runtime |
| Enum comparison `layer_key == "L2-…"` in a CI helper removed in W1 | 1 | 0 | 0 | **false-positive, history-only** — file no longer on `main` |
| **Live or previously-live credential** | **0** | **0** | **0** | — |

**Result: no live secret in the history or current tree of any of the three
repositories.** Every finding is either a hash, a public key, an identifier
or an explicitly synthetic test value.

### 1.3 With `.gitleaks.toml` allowlist (= what CI enforces)

| Repo | History (`--log-opts=--all`) | Current tree |
|---|---|---|
| wakir-runtime | 0 | 0 |
| wakir-protocol | 0 | 0 |
| wakir-verify | 0 | 0 |

Allowlist entries: runtime 7, protocol 3, verify 1. Each entry is scoped to
a path **and** a content shape (`condition = "AND"`) wherever a path is
involved, and carries a justification comment. There is no blanket
`tests/**` or `fixtures/**` allowlist.

## 2. CI gate

`.github/workflows/secret-scan.yml`, identical in all three repos:

- Trigger: `pull_request`, `push` to `main`. Job display name `secret-scan`.
- `permissions: contents: read`. Checkout pinned by commit SHA
  (`actions/checkout@11d5960a…` = v4.4.0), `fetch-depth: 0`.
- Downloads the pinned gitleaks release tarball, verifies the pinned
  SHA-256, runs `gitleaks git --config .gitleaks.toml --redact --exit-code 1`
  over the full history. Output is count-only; finding locations are not
  written to public CI logs — reproduce locally with the same command.
- No `gitleaks-action` (needs an organisation licence key), no TruffleHog
  (AGPL, live credential verification = network egress from CI, `@main` pin).

Negative control (2026-09-11): a throwaway clone of wakir-verify with a
scratch commit holding two canaries — a synthetic AWS-style access-key id and
a freshly generated, never-used Ed25519 PEM private key — fails the same
command with exit 1 (`aws-access-token`, `private-key`); the clean branch
passes with exit 0. The clone was deleted afterwards.

**Branch protection:** adding `secret-scan` to the required status checks of
`main` in all three repos is an operator action (not done by this PR).

## 3. Permissions audit (`contents: write`)

Inventory of workflows declaring more than `contents: read` in wakir-runtime
at `8465c49`: only `resolve-image-pins-ci.yml`.

| Workflow | Permission | Verdict |
|---|---|---|
| `resolve-image-pins-ci.yml` | `contents: write`, `pull-requests: write` | **justified, kept.** The auto-PR step pushes a branch with the job-scoped, ephemeral `GITHUB_TOKEN`; dropping to `read` would require a long-lived PAT or GitHub-App token stored as a repository secret — a worse posture. Blast radius is bounded: `workflow_dispatch` only (no fork/PR-triggered path), auto-PR still needs human review and merge. No `packages: write`, no `id-token: write`. Rationale recorded inline in the workflow's `permissions:` block. |

Per the Phase-4 plan (§5.4, §7) no repo-wide action-SHA pin sweep was
performed; only the three new workflows are SHA-pinned.

## 4. Re-running the scan

```sh
# from a full clone with all refs fetched
gitleaks git --config .gitleaks.toml --log-opts="--all" --redact --exit-code 1 .
gitleaks dir --config .gitleaks.toml --redact --exit-code 1 .
```

Any new finding must be either removed from history (operator decision;
rotate first, then rewrite) or added to `.gitleaks.toml` as a narrow,
justified entry — never suppressed by widening an existing entry.
