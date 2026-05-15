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
#
# Sprint-9 Tag-7 Aenderung (Bug-16 aus Live-Bring-up-3 2026-05-14):
#   - ``resolve_group_tagged`` lief auf ``perl -ne`` / ``perl -pi -e``.
#     Fedora-CoreOS hat KEIN Perl im Host-PATH; der Live-Bring-up
#     crashte mit ``line 280: perl: command not found``, fiel
#     silent durch die Substitution, und bucket-init starb am
#     Placeholder ``DIGEST_PENDING_TOMAS_REVIEW`` mit ``invalid
#     reference format``.
#   - Refactor auf Bash-native (``[[ =~ ]]`` + ``${BASH_REMATCH[@]}``
#     mit Atomic-File-Rewrite via ``mktemp`` + ``mv -f``). Bash 5.x
#     ist FCOS-Standard; kein zusaetzliches Tool-Dependency.
#   - Semantik bleibt identisch zu Tag-6: tag-tolerant, bare-image-
#     tolerant, optional ``--wakir-provisioner-version`` rotation.
#
# Sprint-10 Tag-5 Aenderung (Bug-33 aus M-3 Federation-Live-Trial
# 2026-05-15 15:00 CEST):
#   - Neuer Flag ``--provisioner-only``. In skip-cosign-verify-Mode
#     ruft ``wakir-pilot-bootstrap.sh`` Step 5 den Resolver mit NUR
#     ``--wakir-provisioner-digest`` auf, weil SPIRE+python im
#     skip-cosign-Pfad tag-only laufen (keine @sha256-Substitution
#     in den entsprechenden Quadlet-/Containerfiles). Der Resolver
#     brach mit ``--spire-server-digest is required`` ab, weil
#     validate_digest die drei Haupt-Pins als Pflicht behandelt.
#   - Option-B-Loesung: ``--provisioner-only`` ueberspringt die
#     Validate-Pflicht und die resolve_group-Calls fuer SPIRE+python.
#     Nur die wakir-provisioner-Substitution laeuft. Mira's M-3-
#     Live-Trial verifiziert, dass die SPIRE+python-Containerfiles
#     in skip-cosign-Mode KEINEN @sha256-Placeholder mehr tragen
#     (sie laufen mit Tag-Referenzen), also entfaellt die
#     Substitution dort hard. Aequivalent zu Option-C
#     (FORCE_*_DIGEST env-vars), aber ohne die zusaetzliche
#     env-var-Surface.

set -euo pipefail

PROG=$(basename "$0")

SPIRE_SERVER_DIGEST=""
SPIRE_AGENT_DIGEST=""
PYTHON_DIGEST=""
WAKIR_PROVISIONER_DIGEST=""
WAKIR_PROVISIONER_VERSION=""
PROVISIONER_ONLY=0
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

       OR (Sprint-10 Tag-5 Bug-33 substance-fix path):

       resolve-image-pins.sh
       --provisioner-only
       --wakir-provisioner-digest sha256:<hex>
       [--wakir-provisioner-version <tag>]
       [--root /opt/wakir-runtime]
       [--apply]

Substitutes DIGEST_PENDING_TOMAS_REVIEW placeholders in Quadlet
.container files and in the wakir-provisioner Containerfile FROM
line under <root>.

Without --apply this is a dry-run (no file mutation).

Each digest argument is validated as sha256:<64-hex>.

--wakir-provisioner-digest is OPTIONAL in the full path (Sprint-9
Tag-4 baseline: the operator may not have published the image yet
on first bring-up). Without it, the provisioner Quadlet
substitution is skipped with a WARN-note; Operator-Hand can
re-run the resolver with the flag once the image is published.

--wakir-provisioner-version is OPTIONAL (Sprint-9 Tag-6 addition).
The wakir-provisioner substitution is tag-tolerant: the resolver
matches ``ghcr.io/wakir-labs/wakir-provisioner:<any-tag>@sha256:
DIGEST_PENDING_TOMAS_REVIEW`` and substitutes the real digest
WITHOUT rewriting the tag. Supplying ``--wakir-provisioner-version
<new-tag>`` also rotates the tag in a single pass (useful for the
combined image-rebuild + digest-pin path).

--provisioner-only (Sprint-10 Tag-5 Bug-33): runs ONLY the
wakir-provisioner substitution and skips validate_digest for
--spire-server-digest, --spire-agent-digest, --python-digest. This
is the skip-cosign-verify-mode path: SPIRE+python Quadlets/Containerfiles
run with tag-only references (no @sha256: placeholder), so their
substitution is hard no-op. --wakir-provisioner-digest becomes
REQUIRED in this mode (the only substitution that actually runs).
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
    --provisioner-only)
      PROVISIONER_ONLY=1
      shift
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

# Sprint-10 Tag-5 Bug-33 substance-fix: provisioner-only-Mode skips
# the validate-pflicht for the three non-provisioner digests. In this
# mode, --wakir-provisioner-digest becomes REQUIRED (it is the only
# substitution that runs).
if [[ "$PROVISIONER_ONLY" -eq 1 ]]; then
  if [[ -z "$WAKIR_PROVISIONER_DIGEST" ]]; then
    echo "[$PROG] ERROR: --provisioner-only requires --wakir-provisioner-digest" >&2
    exit 1
  fi
  validate_digest "--wakir-provisioner-digest" "$WAKIR_PROVISIONER_DIGEST"
else
  validate_digest "--spire-server-digest" "$SPIRE_SERVER_DIGEST"
  validate_digest "--spire-agent-digest"  "$SPIRE_AGENT_DIGEST"
  validate_digest "--python-digest"       "$PYTHON_DIGEST"

  # wakir-provisioner is optional in Sprint-9 Tag-4; validate only if
  # supplied.
  if [[ -n "$WAKIR_PROVISIONER_DIGEST" ]]; then
    validate_digest "--wakir-provisioner-digest" "$WAKIR_PROVISIONER_DIGEST"
  fi
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
# Sprint-9 Tag-7 substance-fix (Bug-16, Mira-Bug-Bilanz 2026-05-14):
# the prior implementation used ``perl -ne`` / ``perl -pi -e`` for the
# tag-tolerant regex. Fedora-CoreOS does NOT ship Perl on the host
# PATH; the Live-Bring-up-3 from-scratch run crashed on Step 5 with
# ``line 280: perl: command not found`` and silently fell through to
# the unresolved-placeholder state which crashed bucket-init at step
# 7 with ``invalid reference format``. Refactored to Bash-native:
# Bash 5.x is FCOS-standard, ships in the default OS PATH, and brings
# ERE-with-captures via ``[[ =~ ]]`` + ``${BASH_REMATCH[@]}``.
#
# Implementation: read the file line-by-line, match against an ERE
# anchored on ``image_base`` + optional ``:<tag>`` up to ``@``, and
# rewrite the line via ${BASH_REMATCH[N]} substring substitution. The
# rewritten content lands in a temp-file sibling, which we atomic-mv
# over the original ONLY if the entire pass succeeded (no partial
# rewrite on error).
resolve_group_tagged() {
  local label="$1"
  local image_base="$2"   # e.g. ghcr.io/wakir-labs/wakir-provisioner (NO tag)
  local digest="$3"
  local new_tag="$4"      # optional; empty => preserve existing tag
  shift 4
  local files=("$@")
  local file
  # Bash ERE: '.' is the only image_base meta-char we have to neutralise
  # (the ghcr.io/wakir-labs/<name> shape contains dots and slashes only;
  # '/' is a literal in Bash ERE so it does NOT need escaping). We do
  # NOT escape '/' as that would emit a literal backslash in the regex
  # and the match would fail.
  local escaped_base
  escaped_base=$(printf '%s' "$image_base" | sed 's|\.|\\.|g')
  # Bash ERE for the placeholder line:
  #   <prefix>(<image_base>[:<tag>])@sha256:DIGEST_PENDING_TOMAS_REVIEW<suffix>
  # Capture groups: 1=prefix, 2=base+tag-clause, 3=:<tag> or empty,
  # 4=suffix.
  local rx="^(.*)(${escaped_base}(:[^@[:space:]]+)?)@sha256:DIGEST_PENDING_TOMAS_REVIEW(.*)\$"
  local file_matched
  for file in "${files[@]}"; do
    if [[ ! -f "$file" ]]; then
      echo "[$PROG] WARN: $file not present (skip)"
      continue
    fi
    # First pass: detect whether the file carries any matching line.
    # We do not mutate yet so dry-run + skip-when-absent stay
    # byte-identical to the prior contract.
    file_matched=0
    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
      if [[ "$line" =~ $rx ]]; then
        file_matched=1
        break
      fi
    done < "$file"
    if [[ "$file_matched" -ne 1 ]]; then
      echo "[$PROG] note: $file has no $label placeholder; skip"
      continue
    fi
    # Second pass: build a dry-run preview from the first matching
    # line. We re-read the file (cheap; these are small Quadlet/conf
    # text files) so the preview emission and the apply-pass share a
    # single regex implementation.
    local sample_from="" sample_to="" existing_tag="" tag_clause=""
    while IFS= read -r line || [[ -n "$line" ]]; do
      if [[ "$line" =~ $rx ]]; then
        # ${BASH_REMATCH[2]} is the full image_base[:tag] match.
        sample_from="${BASH_REMATCH[2]}@sha256:DIGEST_PENDING_TOMAS_REVIEW"
        # ${BASH_REMATCH[3]} is ':<tag>' or empty when bare-image.
        existing_tag="${BASH_REMATCH[3]}"
        break
      fi
    done < "$file"
    if [[ -n "$new_tag" ]]; then
      tag_clause=":$new_tag"
    elif [[ -n "$existing_tag" ]]; then
      tag_clause="$existing_tag"
    else
      # Edge case: the placeholder lived on the bare-image form
      # (no tag at all). Substitute digest-only; do not invent a tag.
      tag_clause=""
    fi
    sample_to="${image_base}${tag_clause}@${digest}"
    echo "[$PROG] $label: $file"
    echo "  - $sample_from"
    echo "  + $sample_to"
    if [[ "$APPLY" -eq 1 ]]; then
      # Third pass (apply): rewrite line-by-line into a temp sibling,
      # atomic-mv on success. We deliberately keep the temp-file next
      # to the target so the final mv is rename-on-same-fs (atomic).
      local tmp
      tmp=$(mktemp "${file}.XXXXXX") || {
        echo "[$PROG] ERROR: mktemp next to $file failed" >&2
        return 1
      }
      # Preserve original mode bits on the rewritten file.
      local mode
      mode=$(stat -c '%a' "$file" 2>/dev/null || echo "")
      while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" =~ $rx ]]; then
          local prefix="${BASH_REMATCH[1]}"
          local this_existing_tag="${BASH_REMATCH[3]}"
          local suffix="${BASH_REMATCH[4]}"
          local this_tag_clause
          if [[ -n "$new_tag" ]]; then
            this_tag_clause=":$new_tag"
          elif [[ -n "$this_existing_tag" ]]; then
            this_tag_clause="$this_existing_tag"
          else
            this_tag_clause=""
          fi
          printf '%s%s%s@%s%s\n' \
            "$prefix" "$image_base" "$this_tag_clause" \
            "$digest" "$suffix" >> "$tmp"
        else
          printf '%s\n' "$line" >> "$tmp"
        fi
      done < "$file"
      if [[ -n "$mode" ]]; then
        chmod "$mode" "$tmp" 2>/dev/null || true
      fi
      mv -f "$tmp" "$file" || {
        echo "[$PROG] ERROR: atomic mv $tmp -> $file failed" >&2
        rm -f "$tmp"
        return 1
      }
    fi
  done
}

# Sprint-10 Tag-5 Bug-33 substance-fix: in --provisioner-only mode,
# skip the three non-provisioner resolve_group calls entirely. The
# skip-cosign-verify-mode keeps the SPIRE+python Quadlet/Containerfiles
# at tag-only references (no @sha256: placeholder); attempting a
# substitution here would have been a hard no-op anyway, but the
# validate-pflicht for the empty digest-vars would have already
# aborted the script before reaching this point. Mira's M-3 Live-
# Trial (2026-05-15 15:00 CEST) confirms the skip-cosign path keeps
# bucket-init as the only digest-pinned target.
if [[ "$PROVISIONER_ONLY" -eq 0 ]]; then
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
fi

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
