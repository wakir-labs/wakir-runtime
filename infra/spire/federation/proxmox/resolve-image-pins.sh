#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
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
#     wakir-provisioner:<tag>@sha256:DIGEST_PENDING_TOMAS_REVIEW).
#   - Backwards-compatibility: ``--wakir-provisioner-digest`` ist
#     OPTIONAL. Wird es nicht uebergeben, ueberspringt der
#     Resolver die Provisioner-Substitution mit einer WARN-Note.
#     Operator-Hand kann den Provisioner-Digest spaeter nachsetzen.
#
# Sprint-9 Tag-6 Aenderung (Bug 3 aus Live-Bring-up-2-Bilanz
# 2026-05-14):
#   - Der wakir-provisioner-Image-Prefix matched jetzt
#     ``ghcr.io/wakir-labs/wakir-provisioner`` MIT optionalem
#     ``:<tag>``-Suffix. Die BSL-Bulk-Edit-Welle (PR #37, Commit
#     e5067b4) hat die Quadlet auf ``:0.1.2`` umgestellt, waehrend
#     der Resolver hartkodiert ``:0.1.0`` (kein Tag im Pattern)
#     erwartete. Resultat: Resolver matchte nicht, Placeholder
#     blieb, Bucket-Init-Service crashte mit ``invalid reference
#     format``. Der Fix machte das Pattern tag-tolerant.
#   - ``resolve_group_tagged`` ist eine tag-tolerante Variante von
#     ``resolve_group``; SPIRE-Pins bleiben tag-exact (der Tag ist
#     Teil des Pin-Targets), nur die wakir-provisioner-Substitution
#     toleriert beliebige Tag-Werte.
#   - Optionale neue Flag ``--wakir-provisioner-version`` erlaubt
#     einer spaeteren Resolver-Run eine kombinierte Tag+Digest-
#     Rotation in einem Pass.

set -euo pipefail

PROG=$(basename "$0")

SPIRE_SERVER_DIGEST=""
SPIRE_AGENT_DIGEST=""
PYTHON_DIGEST=""
WAKIR_PROVISIONER_DIGEST=""
WAKIR_PROVISIONER_VERSION=""
ROOT="/opt/wakir-runtime"
APPLY=0

usage() {
  cat <<'EOF'
Usage: resolve-image-pins.sh
       --spire-server-digest sha256:<hex>
       --spire-agent-digest  sha256:<hex>
       --python-digest       sha256:<hex>
       [--wakir-provisioner-digest sha256:<hex>]
       [--wakir-provisioner-version <tag>]
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

--wakir-provisioner-version is OPTIONAL (Sprint-9 Tag-6 addition).
The wakir-provisioner substitution is tag-tolerant: the resolver
matches ``ghcr.io/wakir-labs/wakir-provisioner:<any-tag>@sha256:
DIGEST_PENDING_TOMAS_REVIEW`` and substitutes the real digest
WITHOUT rewriting the tag. Supplying ``--wakir-provisioner-version
<new-tag>`` also rotates the tag in a single pass (useful for the
combined image-rebuild + digest-pin path).
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
    --wakir-provisioner-version)
      WAKIR_PROVISIONER_VERSION="${2:-}"
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

# Sprint-9 Tag-6: validate optional --wakir-provisioner-version when
# supplied. Tags must be a conservative subset of the OCI tag-format
# (semver-ish: [A-Za-z0-9._-]{1,128}); we reject leading dots and
# slashes so an accidentally-pasted full image reference does not
# slip through.
if [[ -n "$WAKIR_PROVISIONER_VERSION" ]]; then
  if ! [[ "$WAKIR_PROVISIONER_VERSION" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$ ]]; then
    echo "[$PROG] ERROR: --wakir-provisioner-version malformed: $WAKIR_PROVISIONER_VERSION" >&2
    exit 1
  fi
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

# resolve_group_tagged is the tag-tolerant variant introduced in
# Sprint-9 Tag-6 for the wakir-provisioner pin (Bug 3 from the Live-
# Bring-up-2-Bilanz 2026-05-14). It accepts the image WITHOUT a tag
# in ``image_base`` and matches the placeholder regardless of which
# tag the Quadlet currently carries:
#
#   ghcr.io/wakir-labs/wakir-provisioner[:<any-tag>]@sha256:DIGEST_PENDING_TOMAS_REVIEW
#
# By default the existing tag is preserved (digest-only substitution).
# When ``new_tag`` is non-empty, the tag is rotated to ``new_tag`` in
# the same pass — this is the combined tag+digest rotation path the
# Operator-Hand re-runs after publishing a fresh image version.
#
# Implementation: a Perl-style in-place edit with a regex anchored on
# ``image_base`` + optional ``:<tag>`` (greedy up to '@'). We use
# perl-style ``-pi`` for the regex; sed -E with backreferences would
# work but the perl form keeps the substitution single-step.
resolve_group_tagged() {
  local label="$1"
  local image_base="$2"   # e.g. ghcr.io/wakir-labs/wakir-provisioner (NO tag)
  local digest="$3"
  local new_tag="$4"      # optional; empty => preserve existing tag
  shift 4
  local files=("$@")
  local file
  # Perl regex: capture optional :<tag>; we never match across '@'.
  # The escaped base lives in the pattern; if image_base contains
  # regex meta-characters this would need fuller escaping, but for
  # the ghcr.io/wakir-labs/<name> shape (dots and slashes only) the
  # only meta-char is '.', which we escape below.
  local escaped_base
  escaped_base=$(printf '%s' "$image_base" | sed 's|\.|\\.|g; s|/|\\/|g')
  local placeholder_token="sha256:DIGEST_PENDING_TOMAS_REVIEW"
  for file in "${files[@]}"; do
    if [[ ! -f "$file" ]]; then
      echo "[$PROG] WARN: $file not present (skip)"
      continue
    fi
    # Pre-check: does the file carry the placeholder under image_base
    # (with any tag, or no tag)? We use perl for the lookahead so the
    # check matches what the substitution will fire on. We export the
    # escaped base into the env so the perl one-liner does not need
    # to do shell-side variable splicing on its regex.
    if ! WAKIR_RESOLVER_RX="$escaped_base" perl -ne '
        BEGIN { $rx = $ENV{WAKIR_RESOLVER_RX} }
        if (/$rx(?::[^@\s]+)?\@sha256:DIGEST_PENDING_TOMAS_REVIEW/) {
          $found = 1;
        }
        END { exit($found ? 0 : 1) }
    ' "$file"; then
      echo "[$PROG] note: $file has no $label placeholder; skip"
      continue
    fi
    # Build a dry-run preview by capturing the first matched line.
    local sample_from sample_to existing_tag replacement_tag_clause
    sample_from=$(WAKIR_RESOLVER_RX="$escaped_base" perl -ne '
        BEGIN { $rx = $ENV{WAKIR_RESOLVER_RX} }
        if (/($rx(?::[^@\s]+)?\@sha256:DIGEST_PENDING_TOMAS_REVIEW)/) {
            print $1;
            exit;
        }
    ' "$file")
    existing_tag=$(printf '%s' "$sample_from" \
      | WAKIR_RESOLVER_RX="$escaped_base" perl -ne '
          BEGIN { $rx = $ENV{WAKIR_RESOLVER_RX} }
          if (/$rx:([^@\s]+)\@/) { print $1 }
      ')
    if [[ -n "$new_tag" ]]; then
      replacement_tag_clause=":$new_tag"
    elif [[ -n "$existing_tag" ]]; then
      replacement_tag_clause=":$existing_tag"
    else
      # Edge case: the placeholder lived on the bare-image form
      # (no tag at all). Substitute digest-only; do not invent a tag.
      replacement_tag_clause=""
    fi
    sample_to="${image_base}${replacement_tag_clause}@${digest}"
    echo "[$PROG] $label: $file"
    echo "  - $sample_from"
    echo "  + $sample_to"
    if [[ "$APPLY" -eq 1 ]]; then
      if [[ -n "$new_tag" ]]; then
        # Tag rotation: rewrite tag AND digest in one pass. Match
        # base + optional :<tag> non-greedily up to '@', then the
        # placeholder. Env-injected replacement to side-step shell-
        # side quoting.
        WAKIR_RESOLVER_RX="$escaped_base" \
        WAKIR_RESOLVER_REPL="${image_base}:${new_tag}@${digest}" \
        perl -pi -e '
          BEGIN {
            $rx   = $ENV{WAKIR_RESOLVER_RX};
            $repl = $ENV{WAKIR_RESOLVER_REPL};
          }
          s/$rx(?::[^@\s]+)?\@sha256:DIGEST_PENDING_TOMAS_REVIEW/$repl/g;
        ' "$file"
      else
        # Digest-only: capture the existing tag (if any) so we keep
        # it byte-identical when substituting. The base + optional
        # tag clause is captured in $1 and re-emitted unchanged.
        WAKIR_RESOLVER_RX="$escaped_base" \
        WAKIR_RESOLVER_DIGEST="$digest" \
        perl -pi -e '
          BEGIN {
            $rx    = $ENV{WAKIR_RESOLVER_RX};
            $dig   = $ENV{WAKIR_RESOLVER_DIGEST};
          }
          s/($rx(?::[^@\s]+)?)\@sha256:DIGEST_PENDING_TOMAS_REVIEW/$1\@$dig/g;
        ' "$file"
      fi
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
  # Sprint-9 Tag-6: tag-tolerant resolver. The Quadlet currently
  # carries ``:0.1.2`` (BSL-1.1 relicense, AR-Decision 2026-05-13)
  # but the Image-Pin form is allowed to drift to a future tag
  # WITHOUT a resolver-side edit. By default we preserve the
  # existing tag and substitute the digest only. If
  # ``--wakir-provisioner-version`` is also supplied we rotate
  # the tag in the same pass.
  resolve_group_tagged \
    "wakir-provisioner" \
    "ghcr.io/wakir-labs/wakir-provisioner" \
    "$WAKIR_PROVISIONER_DIGEST" \
    "$WAKIR_PROVISIONER_VERSION" \
    "${WAKIR_PROVISIONER_FILES[@]}"
else
  echo "[$PROG] WARN: --wakir-provisioner-digest not supplied; skipping"
  echo "[$PROG] WARN: the bucket-init Quadlet keeps the"
  echo "[$PROG] WARN: ghcr.io/wakir-labs/wakir-provisioner:<tag>@sha256:DIGEST_PENDING_TOMAS_REVIEW"
  echo "[$PROG] WARN: placeholder. Re-run the resolver with the flag"
  echo "[$PROG] WARN: once the image is published Operator-Hand."
fi

if [[ "$APPLY" -eq 0 ]]; then
  echo "[$PROG] dry-run; no file mutation. Re-run with --apply to commit."
else
  echo "[$PROG] applied."
fi
