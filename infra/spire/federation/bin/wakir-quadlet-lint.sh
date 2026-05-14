#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Sprint-9-Tag-9 Bug-23 substance-fix: Quadlet-Lint pre-check.
#
# This wrapper invokes ``/usr/libexec/podman/quadlet --dryrun`` against
# the substituted Wakir Quadlet inventory and exits non-zero on any
# parse/structural error. Designed as a hermetic, sandbox-friendly,
# free-of-cost CI gate that closes the Live-Bring-up-Sandbox-Gap class
# of bugs that has now hit the pilot four bring-ups in a row:
#
#   * Bug-20 (Tag-8): missing ``:Z`` flags on named-volume mounts.
#   * Bug-21 (Tag-8): chown stderr swallow + missing stat verification.
#   * Bug-22 (Tag-9): TOC-vs-TOU race between ad-hoc volume create and
#                     podman-system-generator reconcile.
#   * Bug-23 itself: forecast — any future Volume= syntax slip,
#                    missing dependency, malformed Image= line, etc.
#                    would silently land in main and only blow up on
#                    a live VM. This gate catches them at PR time.
#
# Substitution
# ------------
#
# The Phase-2 SPIRE-Federation templates contain ``<SIDE>``,
# ``<TRUST_DOMAIN>``, ``<SERVER_DNS>``, ``<HOST_BUNDLE_PORT>``,
# ``<HOST_GRPC_PORT>`` placeholders that the bootstrap script
# substitutes at install time. The Quadlet generator does not know
# about these placeholders and reports them as missing-volume
# references. We mirror the bootstrap's substitution into a tmp
# staging dir and run the dryrun against that.
#
# We exercise both ``wakir`` and ``partner`` sides — the partner-side
# is a strict mirror of the wakir-side under the dual-trust-domain
# bring-up that lands in Phase-2.1, and any drift between the two
# substitution paths is itself a regression.
#
# Exit codes
# ----------
#
#   0   all units parse cleanly
#   2   one or more units fail to parse (caller MUST treat as failure)
#   3   podman quadlet binary missing — caller may skip with a warning
#
# Hermetic posture: the script touches /tmp only; no /etc/containers
# write, no systemd daemon-reload, no live volumes/networks/containers
# created. Pure source-level lint.
#
# -- Tomás

set -euo pipefail

PROG=${0##*/}
QUADLET_BIN=${QUADLET_BIN:-/usr/libexec/podman/quadlet}
REPO_ROOT=${WAKIR_REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}

if [[ ! -x "$QUADLET_BIN" ]]; then
  echo "$PROG: ERROR: podman quadlet binary not found at $QUADLET_BIN" >&2
  echo "$PROG: install podman >= 4.4 to obtain /usr/libexec/podman/quadlet" >&2
  exit 3
fi

# Sanity: make sure the source dirs we expect actually exist.
TOP_QUADLET=$REPO_ROOT/quadlet
FED_QUADLET=$REPO_ROOT/infra/spire/federation/quadlet
AGT_QUADLET=$REPO_ROOT/infra/spire/agent/quadlet

for d in "$TOP_QUADLET" "$FED_QUADLET" "$AGT_QUADLET"; do
  if [[ ! -d "$d" ]]; then
    echo "$PROG: ERROR: expected Quadlet source dir missing: $d" >&2
    exit 2
  fi
done

# Build a staging dir per side that mirrors the bootstrap's substituted
# install. The Quadlet generator looks for Volume= / Image= cross-refs
# inside QUADLET_UNIT_DIRS — we flatten all three source trees into one
# dir per side so the generator can resolve them.
STAGING=$(mktemp -d -t wakir-quadlet-lint-XXXXXX)
trap 'rm -rf "$STAGING"' EXIT

stage_for_side() {
  local side=$1
  local trust_domain=$2
  local server_dns=$3
  local out=$STAGING/$side
  mkdir -p "$out"

  # 1) Top-level (side-agnostic) quadlets — copy as-is.
  local f
  for f in "$TOP_QUADLET"/*.container "$TOP_QUADLET"/*.volume \
           "$TOP_QUADLET"/*.network; do
    [[ -f "$f" ]] || continue
    cp "$f" "$out/$(basename "$f")"
  done

  # 2) Federation-server templates — sed-substitute and rename to
  #    embed the side token (mirror of bootstrap step 6b-ii).
  for f in "$FED_QUADLET"/*.volume; do
    [[ -f "$f" ]] || continue
    local base dest
    base=$(basename "$f")
    dest=$(printf '%s' "$base" \
      | sed "s/^wakir-spire-server-federation-\(data\|sockets\|bundles\)\.volume$/wakir-spire-server-federation-${side}-\1.volume/")
    sed -e "s/<SIDE>/${side}/g" "$f" > "$out/$dest"
  done

  if [[ -f "$FED_QUADLET/wakir-spire-server-federation.container" ]]; then
    sed -e "s/<SIDE>/${side}/g" \
        -e "s/<HOST_BUNDLE_PORT>/8443/g" \
        -e "s/<HOST_GRPC_PORT>/8082/g" \
        "$FED_QUADLET/wakir-spire-server-federation.container" \
      > "$out/wakir-spire-server-federation-${side}.container"
  fi

  if [[ -f "$FED_QUADLET/wakir-federation.network" ]]; then
    cp "$FED_QUADLET/wakir-federation.network" "$out/"
  fi

  # 3) Agent templates — drop ``federation-`` token from basename
  #    (mirror of bootstrap step 6b-iii).
  for f in "$AGT_QUADLET"/*.volume; do
    [[ -f "$f" ]] || continue
    local base dest
    base=$(basename "$f")
    dest=$(printf '%s' "$base" \
      | sed "s/^wakir-spire-agent-federation-\(data\|sockets\)\.volume$/wakir-spire-agent-${side}-\1.volume/")
    sed -e "s/<SIDE>/${side}/g" "$f" > "$out/$dest"
  done

  if [[ -f "$AGT_QUADLET/wakir-spire-agent-federation.container" ]]; then
    sed -e "s|<SIDE>|${side}|g" \
        -e "s|<TRUST_DOMAIN>|${trust_domain}|g" \
        -e "s|<SERVER_DNS>|${server_dns}|g" \
        "$AGT_QUADLET/wakir-spire-agent-federation.container" \
      > "$out/wakir-spire-agent-${side}.container"
  fi

  printf '%s\n' "$out"
}

stage_wakir=$(stage_for_side "wakir" "wakir.test" "spire-server-wakir")
stage_partner=$(stage_for_side "partner" "partner.test" "spire-server-partner")

run_dryrun_for_side() {
  local side=$1
  local stage_dir=$2
  local log
  log=$(mktemp -t wakir-quadlet-lint-${side}-XXXXXX.log)
  if QUADLET_UNIT_DIRS=$stage_dir "$QUADLET_BIN" --dryrun >"$log" 2>&1; then
    rm -f "$log"
    echo "$PROG: side=${side} OK"
    return 0
  fi
  echo "$PROG: ERROR: side=${side} Quadlet dryrun reported errors:" >&2
  # Show the diagnostic lines (the generator emits one stderr line per
  # converted unit plus a final summary; we surface anything matching
  # known error fragments).
  grep -E "error|Error|ERROR|invalid|Invalid|fail|Fail|requested Quadlet source" "$log" \
    | head -30 >&2 || true
  echo "$PROG: ERROR: side=${side} staging dir: $stage_dir" >&2
  echo "$PROG: ERROR: side=${side} full log: $log" >&2
  return 2
}

rc=0
run_dryrun_for_side "wakir"   "$stage_wakir"   || rc=$?
run_dryrun_for_side "partner" "$stage_partner" || rc=$?

if [[ "$rc" -ne 0 ]]; then
  exit "$rc"
fi

echo "$PROG: all sides OK ($(ls "$stage_wakir" | wc -l) units / side)"
exit 0
