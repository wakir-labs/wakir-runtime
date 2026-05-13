#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-9 Tag-1 — Reproducible Proxmox-bundle builder.
#
# Produces:
#   infra/spire/federation/proxmox/proxmox-bundle-v1.0.tar.gz
#   infra/spire/federation/proxmox/proxmox-bundle-v1.0.sha256
#
# Output hash is stable across repeated invocations:
#   * mtime normalised to 1970-01-01T00:00:00Z
#   * uid/gid set to 0/0 (root) in the archive
#   * sorted file ordering (tar --sort=name)
#   * gzip -n (no embedded mtime)
#
# Bundle scope (minimal for the Phase-1b single-org pilot):
#   wakir-runtime/quadlet/
#   wakir-runtime/infra/spire/
#   wakir-runtime/bin/
#   wakir-runtime/wirelang/federation/marker_stack_kv.py
#   wakir-runtime/wirelang/federation/__init__.py
#   wakir-runtime/wirelang/__init__.py
#   wakir-runtime/conftest.py
#   wakir-runtime/LICENSE
#   wakir-runtime/NOTICE
#
# Sandbox-Grenze: dieses Skript laeuft auf einem Repo-Klon (CI oder
# Operator-Workstation), nicht in der Pilot-VM. Hermetic-Test in
# tests/orchestrator/test_proxmox_build_bundle.py validates the
# inclusion-list invariants without actually tarring anything.

set -euo pipefail

PROG=$(basename "$0")
HERE=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$HERE/../../../.." && pwd)

OUT="$HERE/proxmox-bundle-v1.0.tar.gz"
SHA="$HERE/proxmox-bundle-v1.0.sha256"

if [[ ! -d "$REPO_ROOT/quadlet" ]] || [[ ! -d "$REPO_ROOT/infra/spire" ]]; then
  echo "[$PROG] ERROR: repo root looks wrong: $REPO_ROOT" >&2
  exit 1
fi

# Stage a deterministic copy into a temp dir.
STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT

stage() {
  local relpath="$1"
  local target="$STAGE/wakir-runtime/$relpath"
  mkdir -p "$(dirname "$target")"
  if [[ -d "$REPO_ROOT/$relpath" ]]; then
    cp -r "$REPO_ROOT/$relpath" "$(dirname "$target")"
  else
    cp "$REPO_ROOT/$relpath" "$target"
  fi
}

# Drop the bundle's own output artefacts if they were staged.
strip_self() {
  local sf
  for sf in \
    "$STAGE/wakir-runtime/infra/spire/federation/proxmox/proxmox-bundle-v1.0.tar.gz" \
    "$STAGE/wakir-runtime/infra/spire/federation/proxmox/proxmox-bundle-v1.0.sha256" \
  ; do
    rm -f "$sf"
  done
}

stage "quadlet"
stage "infra/spire"
stage "bin"
stage "wirelang/__init__.py"
stage "wirelang/federation/__init__.py"
stage "wirelang/federation/marker_stack_kv.py"
stage "wirelang/federation/n2_evaluator.py"
stage "wirelang/federation/marker_composition.py"
stage "wirelang/federation/cross_org_attenuation_verifier.py"
stage "conftest.py"
stage "LICENSE"
stage "NOTICE"

# Drop the bundle's own output artefacts (if present) before tarring.
strip_self

# Drop python cache artefacts that ride along with cp -r.
find "$STAGE" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "$STAGE" -type f -name '*.pyc' -delete

# Normalise mtime + permissions for reproducibility.
find "$STAGE" -exec touch -h -d '@0' {} + 2>/dev/null || true

# Tar with deterministic ordering. --mtime requires GNU tar.
( cd "$STAGE" && \
  tar \
    --sort=name \
    --owner=0 --group=0 --numeric-owner \
    --mtime='1970-01-01 00:00:00 UTC' \
    --format=ustar \
    -cf - wakir-runtime ) \
  | gzip -n -9 > "$OUT"

sha256sum "$OUT" | awk '{print $1}' > "$SHA"

echo "[$PROG] wrote: $OUT"
echo "[$PROG] sha256: $(cat "$SHA")"
