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
#       --wakir-provisioner-digest sha256:<hex> \
#       --root /opt/wakir-runtime \
#       [--apply]
#
# Ohne --apply: zeigt nur an, welche Dateien betroffen waeren.
# Mit --apply: ersetzt in-place; sed -i ohne Backup.
#
# Sandbox-Grenze: dieses Skript laeuft auf der Pilot-VM, nicht in
# der Sandbox. Hermetic-Test in tests/orchestrator/test_proxmox_
# resolve_image_pins.py exercising the substitution logic.
#
# Sprint-9 Tag-4 Aenderung:
#   - Der ``python:3.13-slim``-Pin ist von der Quadlet zur
#     ``wakir-provisioner/Containerfile`` FROM-Line gewandert.
#     ``--python-digest`` setzt den Pin jetzt in der Containerfile.
#   - Neuer Pin ``--wakir-provisioner-digest`` ersetzt den
#     Platzhalter in der Quadlet (Image=ghcr.io/wakir-labs/
#     wakir-provisioner:0.1.0@sha256:DIGEST_PENDING_TOMAS_REVIEW).
#   - Backwards-compatibility: ``--wakir-provisioner-digest`` ist
#     OPTIONAL. Wird es nicht uebergeben, ueberspringt der
#     Resolver die Provisioner-Substitution mit einer WARN-Note.
#     Operator-Hand kann den Provisioner-Digest spaeter nachsetzen.

set -euo pipefail

PROG=$(basename "$0")

SPIRE_SERVER_DIGEST=""
SPIRE_AGENT_DIGEST=""
PYTHON_DIGEST=""
WAKIR_PROVISIONER_DIGEST=""
ROOT="/opt/wakir-runtime"
APPLY=0

usage() {
  cat <<'EOF'
Usage: resolve-image-pins.sh
       --spire-server-digest sha256:<hex>
       --spire-agent-digest  sha256:<hex>
       --python-digest       sha256:<hex>
       [--wakir-provisioner-digest sha256:<hex>]
       [--root /opt/wakir-runtime]
       [--apply]

Substitutes DIGEST_PENDING_TOMAS_REVIEW placeholders in Quadlet
.container files and in the wakir-provisioner Containerfile FROM
line under <root>.

Without --apply this is a dry-run (no file mutation).

Each digest argument is validated as sha256:<64-hex>.

--wakir-provisioner-digest is OPTIONAL (Sprint-9 Tag-4 baseline:
the operator may not have published the image yet on first bring-
up). Without it, the provisioner Quadlet substitution is skipped
with a WARN-note; Operator-Hand can re-run the resolver with the
flag once the image is published.
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
    --wakir-provisioner-digest)
      WAKIR_PROVISIONER_DIGEST="${2:-}"
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

# wakir-provisioner is optional in Sprint-9 Tag-4; validate only if
# supplied.
if [[ -n "$WAKIR_PROVISIONER_DIGEST" ]]; then
  validate_digest "--wakir-provisioner-digest" "$WAKIR_PROVISIONER_DIGEST"
fi

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
# Sprint-9 Tag-4: python:3.13-slim is no longer pinned by the
# Quadlet directly; it lives in the wakir-provisioner Containerfile.
declare -a PYTHON_FILES=(
  "$ROOT/infra/spire/federation/provisioner/Containerfile"
)
# Sprint-9 Tag-4: new pin target — the published wakir-provisioner
# image. Substituted into the bucket-init Quadlet.
declare -a WAKIR_PROVISIONER_FILES=(
  "$ROOT/quadlet/wakir-nats-kv-bucket-init.container"
)

# resolve_group performs sed substitution against any line that
# carries ``<image_prefix>@sha256:DIGEST_PENDING_TOMAS_REVIEW``. The
# match is intentionally directive-agnostic so the SAME function
# handles both Quadlet ``Image=`` lines and Containerfile ``FROM``
# lines (Sprint-9 Tag-4: the python pin moved across that boundary).
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
    local from="${image_prefix}@sha256:DIGEST_PENDING_TOMAS_REVIEW"
    local to="${image_prefix}@${digest}"
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

if [[ -n "$WAKIR_PROVISIONER_DIGEST" ]]; then
  resolve_group \
    "wakir-provisioner" \
    "ghcr.io/wakir-labs/wakir-provisioner:0.1.0" \
    "$WAKIR_PROVISIONER_DIGEST" \
    "${WAKIR_PROVISIONER_FILES[@]}"
else
  echo "[$PROG] WARN: --wakir-provisioner-digest not supplied; skipping"
  echo "[$PROG] WARN: the bucket-init Quadlet keeps the"
  echo "[$PROG] WARN: ghcr.io/wakir-labs/wakir-provisioner@sha256:DIGEST_PENDING_TOMAS_REVIEW"
  echo "[$PROG] WARN: placeholder. Re-run the resolver with the flag"
  echo "[$PROG] WARN: once the image is published Operator-Hand."
fi

if [[ "$APPLY" -eq 0 ]]; then
  echo "[$PROG] dry-run; no file mutation. Re-run with --apply to commit."
else
  echo "[$PROG] applied."
fi
