#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-9 Tag-5 — Idempotent CI-side image-pin resolver.
#
# Companion to ``infra/spire/federation/proxmox/resolve-image-pins.sh``
# (which is the Operator-Hand VM-side resolver). This script is the
# CI-side variant: it runs from the GitHub-Actions
# ``resolve-image-pins-ci`` workflow against the live registry, decides
# whether ANY pin in the repo needs an update, and exits with a
# distinct code so the workflow knows whether to open a PR.
#
# Why a CI-side resolver at all
# -----------------------------
# The Operator-Hand resolver runs on the Pilot-VM as part of the
# bring-up. It mutates files on the VM, not in the repo. The repo
# pins still carry ``DIGEST_PENDING_TOMAS_REVIEW`` until someone
# Operator-Hand opens a follow-up PR with the resolved digests.
# That follow-up has historically been ad-hoc and easy to forget.
#
# This CI-side resolver closes that gap:
#   * workflow_dispatch (manual) — operator clicks "Run workflow"
#     after publishing a new image.
#   * schedule (cron) — weekly drift check; if an upstream re-push
#     changed a stable tag's digest, we open a PR within hours.
#
# Idempotency contract
# --------------------
# A "re-run" with the same target digest MUST produce no file
# mutation. Idempotency is the whole point: a cron run that does not
# discover a drift must NOT churn the repo with no-op commits.
#
# The resolver therefore:
#   1. Reads the current pin from each target file (digest token).
#   2. Compares it against the freshly resolved live digest.
#   3. If they match, skips the file (no mutation, no log noise).
#   4. If they differ, substitutes and increments a "drift" counter.
#   5. Exits 0 if drift_count == 0, exits 10 if drift_count > 0.
#      (10 is a sentinel — the workflow uses it to decide whether to
#      open a PR. exit 1 stays reserved for "real" errors.)
#
# Sandbox boundary
# ----------------
# This script is meant for the GitHub-Actions runner (host-of-record),
# not for the claude-dev sandbox. Hermetic tests stub crane out via
# ``--digest-source`` to keep network egress out of the sandbox per
# feedback_sandbox_host_trennung.md.

set -euo pipefail

PROG=$(basename "$0")

# ----------------------------------------------------------------------
# Argument parsing.
# ----------------------------------------------------------------------

ROOT="$(pwd)"
DIGEST_SOURCE="crane"        # crane (live) | env (testing)
PRINT_ONLY=0                 # 1 = compute drift, do not mutate files
EXIT_ON_DRIFT=10             # sentinel for "drift detected"

declare -A FORCED_DIGESTS    # set by --digest-source env via FORCE_*_DIGEST

usage() {
  cat <<'EOF'
Usage: image-pin-idempotent-resolver.sh
       [--root <path>]
       [--digest-source crane|env]
       [--print-only]

Walks the four pin targets in the repo and resolves any drift between
the committed digest and the live (or forced) digest. Re-runs on a
stable repo state are no-ops by construction.

--root           : repo root (default: cwd)
--digest-source  : ``crane`` (default; fetches live digests) or
                   ``env`` (reads FORCE_<group>_DIGEST env vars; used
                   by hermetic tests to avoid network egress).
--print-only     : compute the drift table and print it, do not
                   modify any files.

Exit codes:
  0   = no drift (idempotent re-run)
  10  = drift detected (workflow should open a PR)
  1+  = real error (bad args, missing files, unreachable registry)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root)
      ROOT="${2:-}"
      shift 2
      ;;
    --digest-source)
      DIGEST_SOURCE="${2:-}"
      shift 2
      ;;
    --print-only)
      PRINT_ONLY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[$PROG] ERROR: unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$DIGEST_SOURCE" in
  crane|env) : ;;
  *)
    echo "[$PROG] ERROR: --digest-source must be crane or env" >&2
    exit 1
    ;;
esac

if [[ ! -d "$ROOT" ]]; then
  echo "[$PROG] ERROR: --root $ROOT not a directory" >&2
  exit 1
fi

# ----------------------------------------------------------------------
# Pin inventory — keep in sync with
# infra/spire/federation/IMAGE_PINS.md §1 and the Operator-Hand
# resolver's file-group declaration.
# ----------------------------------------------------------------------

# Format: <group_key>|<image_prefix>|<file1>[;<file2>...]
#
# Sprint-9 Tag-6: the wakir-provisioner row uses the BARE image-base
# (no ``:<tag>`` suffix) so the resolver is tag-tolerant — the BSL-
# Bulk-Edit-Welle (PR #37) drifted the Quadlet tag from ``:0.1.0``
# to ``:0.1.2`` and the previous hardcoded ``:0.1.2`` prefix would
# break the next time the tag rotates. The extractor honours the
# bare-base form by accepting an optional ``:<tag>`` between base
# and ``@sha256:`` (see ``extract_current_digest`` + the line-
# level grep). The SPIRE and python rows stay tag-pinned because
# their tag is upstream-fixed (SPIRE release line, python minor).
PINS=(
  "spire_server|ghcr.io/spiffe/spire-server:1.14.6|infra/spire/federation/quadlet/wakir-spire-server-federation.container;quadlet/wakir-spire-server.container"
  "spire_agent|ghcr.io/spiffe/spire-agent:1.14.6|infra/spire/agent/quadlet/wakir-spire-agent-federation.container;quadlet/wakir-spire-agent.container"
  "python|docker.io/library/python:3.13-slim|infra/spire/federation/provisioner/Containerfile"
  "wakir_provisioner|ghcr.io/wakir-labs/wakir-provisioner|quadlet/wakir-nats-kv-bucket-init.container"
)

# ----------------------------------------------------------------------
# Digest fetching.
# ----------------------------------------------------------------------

fetch_live_digest() {
  local group_key="$1"
  local image_ref="$2"   # e.g. ghcr.io/spiffe/spire-server:1.14.6
  case "$DIGEST_SOURCE" in
    crane)
      crane digest "$image_ref"
      ;;
    env)
      # Hermetic-test path: read FORCE_<UPPER>_DIGEST.
      local upper
      upper=$(echo "$group_key" | tr '[:lower:]' '[:upper:]')
      local var="FORCE_${upper}_DIGEST"
      local val="${!var:-}"
      if [[ -z "$val" ]]; then
        echo "[$PROG] WARN: $var not set in env-mode; skipping group $group_key" >&2
        return 1
      fi
      echo "$val"
      ;;
  esac
}

# ----------------------------------------------------------------------
# Pin extraction + comparison.
# ----------------------------------------------------------------------

extract_current_digest() {
  # Pulls the sha256:<hex> (or the placeholder token) currently
  # committed for <image_prefix> in <file>. Empty stdout = no match.
  #
  # Sprint-9 Tag-6: the image_prefix may be EITHER tag-pinned
  # (``ghcr.io/spiffe/spire-server:1.14.6``) OR bare-base
  # (``ghcr.io/wakir-labs/wakir-provisioner``). In the bare-base
  # case we tolerate an arbitrary ``:<tag>`` between the prefix and
  # the ``@sha256:`` segment so a downstream tag-rotation does not
  # silently break drift detection. In the tag-pinned case the
  # regex still anchors on the exact prefix because the prefix
  # already carries the ``:<tag>``.
  local file="$1"
  local image_prefix="$2"
  grep -oE "${image_prefix//./\\.}(:[^@[:space:]\"']+)?@(sha256:[a-f0-9]{64}|sha256:DIGEST_PENDING_TOMAS_REVIEW)" "$file" \
    | head -n1 \
    | sed -E "s|^${image_prefix//./\\.}(:[^@[:space:]\"']+)?@||"
}

extract_current_tag() {
  # Pulls the tag currently committed between <image_prefix> and
  # ``@sha256:`` in <file>. Empty stdout = no tag in the
  # pin-string (the prefix already carried the tag, or the pin is
  # bare-base). Used by the bare-base substitution path to preserve
  # the existing tag byte-for-byte.
  local file="$1"
  local image_prefix="$2"
  grep -oE "${image_prefix//./\\.}(:[^@[:space:]\"']+)?@(sha256:[a-f0-9]{64}|sha256:DIGEST_PENDING_TOMAS_REVIEW)" "$file" \
    | head -n1 \
    | sed -nE "s|^${image_prefix//./\\.}:([^@[:space:]\"']+)@.*$|\1|p"
}

drift_count=0
no_op_count=0
missing_count=0

# Mutual-exclusion lock-free: each file is touched at most once per
# group, so re-entrant calls are safe.

for entry in "${PINS[@]}"; do
  IFS='|' read -r group_key image_prefix files_joined <<<"$entry"
  IFS=';' read -ra files <<<"$files_joined"

  live=""
  if ! live=$(fetch_live_digest "$group_key" "$image_prefix" 2>/dev/null); then
    echo "[$PROG] skip group $group_key (digest source unreachable)"
    continue
  fi
  if ! [[ "$live" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "[$PROG] ERROR: $group_key live digest malformed: $live" >&2
    exit 1
  fi

  for file in "${files[@]}"; do
    full="$ROOT/$file"
    if [[ ! -f "$full" ]]; then
      echo "[$PROG] note: $file not present; skip"
      missing_count=$((missing_count+1))
      continue
    fi

    current=$(extract_current_digest "$full" "$image_prefix" || true)
    if [[ -z "$current" ]]; then
      echo "[$PROG] note: $file has no $group_key pin; skip"
      continue
    fi

    if [[ "$current" == "$live" ]]; then
      # IDEMPOTENT CASE — the committed pin is already correct. This
      # is the path a daily cron run lands on 99% of the time.
      no_op_count=$((no_op_count+1))
      continue
    fi

    # Drift — either placeholder, or stale digest.
    echo "[$PROG] drift: $file"
    echo "  group:   $group_key"
    echo "  image:   $image_prefix"
    echo "  before:  $current"
    echo "  after:   $live"
    drift_count=$((drift_count+1))

    if [[ "$PRINT_ONLY" -eq 0 ]]; then
      # Substitute in-place. The pattern is anchored to
      # ``<image_prefix>[:<tag>]@<current>`` so we cannot
      # accidentally rewrite an unrelated digest line. When the
      # PINS entry is bare-base (Sprint-9 Tag-6, wakir-provisioner),
      # we preserve the existing ``:<tag>`` byte-for-byte so a
      # digest rotation never silently strips the tag.
      existing_tag=$(extract_current_tag "$full" "$image_prefix")
      if [[ -n "$existing_tag" ]]; then
        from="${image_prefix}:${existing_tag}@${current}"
        to="${image_prefix}:${existing_tag}@${live}"
      else
        from="${image_prefix}@${current}"
        to="${image_prefix}@${live}"
      fi
      sed -i "s|${from}|${to}|g" "$full"
    fi
  done
done

# ----------------------------------------------------------------------
# Summary + exit-code contract.
# ----------------------------------------------------------------------

echo ""
echo "[$PROG] summary:"
echo "  no-op (idempotent): $no_op_count"
echo "  drift detected:     $drift_count"
echo "  missing files:      $missing_count"

if [[ "$drift_count" -eq 0 ]]; then
  echo "[$PROG] OK: all pins already match live digests; no-op re-run."
  exit 0
fi

if [[ "$PRINT_ONLY" -eq 1 ]]; then
  echo "[$PROG] drift detected ($drift_count groups); --print-only, no files mutated."
else
  echo "[$PROG] drift applied to $drift_count file(s); workflow should open a PR."
fi
exit "$EXIT_ON_DRIFT"
