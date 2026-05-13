#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-9 Tag-1 — Image-Pin-Placeholder-Resolution-Skript fuer
# den Proxmox-VM Bring-up. Loest die Operator-Hand-Pflicht
# ``DIGEST_PENDING_TOMAS_REVIEW``-Token in den Quadlet-Templates auf
# echte sha256-Digests (Cross-Review Zone-C).
#
# Aufruf:
#   ./resolve-image-pins.sh \
#       --spire-server-digest sha256:<hex> \
#       --spire-agent-digest sha256:<hex> \
#       --python-digest sha256:<hex> \
#       --root /opt/wakir-runtime \
#       [--apply]
#
# Ohne --apply: zeigt nur an, welche Dateien betroffen waeren.
# Mit --apply: ersetzt in-place; sed -i ohne Backup.
#
# Sandbox-Grenze: dieses Skript laeuft auf der Pilot-VM, nicht in
# der Sandbox. Hermetic-Test in tests/orchestrator/test_proxmox_
# resolve_image_pins.py exercising the substitution logic.

set -euo pipefail

PROG=$(basename "$0")

SPIRE_SERVER_DIGEST=""
SPIRE_AGENT_DIGEST=""
PYTHON_DIGEST=""
ROOT="/opt/wakir-runtime"
APPLY=0

usage() {
  cat <<'EOF'
Usage: resolve-image-pins.sh
       --spire-server-digest sha256:<hex>
       --spire-agent-digest  sha256:<hex>
       --python-digest       sha256:<hex>
       [--root /opt/wakir-runtime]
       [--apply]

Substitutes DIGEST_PENDING_TOMAS_REVIEW placeholders in Quadlet
.container files under <root>/quadlet/ and <root>/infra/spire/.

Without --apply this is a dry-run (no file mutation).

Each digest argument is validated as sha256:<64-hex>.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --spire-server-digest)
      SPIRE_SERVER_DIGEST="${2:-}"
      shift 2
      ;;
    --spire-agent-digest)
      SPIRE_AGENT_DIGEST="${2:-}"
      shift 2
      ;;
    --python-digest)
      PYTHON_DIGEST="${2:-}"
      shift 2
      ;;
    --root)
      ROOT="${2:-}"
      shift 2
      ;;
    --apply)
      APPLY=1
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

validate_digest() {
  local label="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "[$PROG] ERROR: $label is required" >&2
    exit 1
  fi
  if ! [[ "$value" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "[$PROG] ERROR: $label malformed (expect sha256:<64-hex>): $value" >&2
    exit 1
  fi
}

validate_digest "--spire-server-digest" "$SPIRE_SERVER_DIGEST"
validate_digest "--spire-agent-digest"  "$SPIRE_AGENT_DIGEST"
validate_digest "--python-digest"       "$PYTHON_DIGEST"

if [[ ! -d "$ROOT" ]]; then
  echo "[$PROG] ERROR: --root $ROOT not a directory" >&2
  exit 1
fi

# Target file groups (image-name → digest variable).
declare -a SERVER_FILES=(
  "$ROOT/quadlet/wakir-spire-server.container"
  "$ROOT/infra/spire/federation/quadlet/wakir-spire-server-federation.container"
)
declare -a AGENT_FILES=(
  "$ROOT/quadlet/wakir-spire-agent.container"
  "$ROOT/infra/spire/agent/quadlet/wakir-spire-agent-federation.container"
)
declare -a PYTHON_FILES=(
  "$ROOT/quadlet/wakir-nats-kv-bucket-init.container"
)

resolve_group() {
  local label="$1"
  local image_prefix="$2"   # e.g. ghcr.io/spiffe/spire-server:1.14.6
  local digest="$3"
  shift 3
  local files=("$@")
  local file
  for file in "${files[@]}"; do
    if [[ ! -f "$file" ]]; then
      echo "[$PROG] WARN: $file not present (skip)"
      continue
    fi
    if ! grep -q "${image_prefix}@sha256:DIGEST_PENDING_TOMAS_REVIEW" "$file"; then
      echo "[$PROG] note: $file has no $label placeholder; skip"
      continue
    fi
    local from="Image=${image_prefix}@sha256:DIGEST_PENDING_TOMAS_REVIEW"
    local to="Image=${image_prefix}@${digest}"
    echo "[$PROG] $label: $file"
    echo "  - $from"
    echo "  + $to"
    if [[ "$APPLY" -eq 1 ]]; then
      sed -i "s|${from}|${to}|g" "$file"
    fi
  done
}

resolve_group \
  "spire-server" \
  "ghcr.io/spiffe/spire-server:1.14.6" \
  "$SPIRE_SERVER_DIGEST" \
  "${SERVER_FILES[@]}"

resolve_group \
  "spire-agent" \
  "ghcr.io/spiffe/spire-agent:1.14.6" \
  "$SPIRE_AGENT_DIGEST" \
  "${AGENT_FILES[@]}"

resolve_group \
  "python" \
  "docker.io/library/python:3.13-slim" \
  "$PYTHON_DIGEST" \
  "${PYTHON_FILES[@]}"

if [[ "$APPLY" -eq 0 ]]; then
  echo "[$PROG] dry-run; no file mutation. Re-run with --apply to commit."
else
  echo "[$PROG] applied."
fi
