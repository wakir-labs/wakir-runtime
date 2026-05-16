#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Sprint-10 Tag-9 — Canonical Wakir-Pilot Acceptance Entry-Point.
#
# Why this script exists
# ----------------------
#
# Sprint-10 Tag-6/8 (Bug-30..33, Bug-36+37, Bug-38) iterated the
# Live-VM-Acceptance lane against ``scripts/federation-live-vm-
# acceptance.sh``. The script grew the federation-mode-specific shape
# (Phase 2 federation-unit probes, Phase 3 smoke-fed-gate) and is
# locked to ``WAKIR_PILOT_MODE=federation``. Tag-9 hermetic-substrate
# review (Mira-CEO Tag-9 auftrag, 2026-05-15) found that the
# acceptance entry-point naming is asymmetric with the wider
# convention:
#
# * The hermetic-substrate convention is
#   ``scripts/acceptance/<canonical-name>.sh`` (mirroring
#   ``scripts/systemd/`` and ``infra/spire/agent/quadlet/``).
# * The federation-specific acceptance lane sits at the flat
#   ``scripts/`` root, which makes single-org acceptance discovery
#   awkward (no clear "what acceptance script do I run?" path for
#   the single-org pilot variant).
#
# This script is the canonical entry-point that dispatches by
# ``WAKIR_PILOT_MODE``:
#
# * ``WAKIR_PILOT_MODE=federation`` (default) → forwards to
#   ``scripts/federation-live-vm-acceptance.sh`` with all env-vars
#   propagated. The federation script is the substantive lane;
#   this is a pure dispatch (no logic-clone, no drift surface).
#
# * ``WAKIR_PILOT_MODE=single-org`` → runs a thin single-org
#   acceptance probe inline: bootstrap-re-run + 3-check single-org
#   verification (server-unit + agent-unit + smoke-test). The
#   single-org substrate is simpler than federation (no bundle-
#   endpoint, no peer-side, no cross-trust-domain handshake), so
#   the probe is a few lines here rather than a separate script.
#
# Sandbox boundary
# ----------------
#
# Same as ``federation-live-vm-acceptance.sh``: this script DOES NOT
# run in the claude-dev Sandbox. It runs on an operator-controlled
# host (Mira-Hand) that has SSH access to the Pilot-VM. The Sandbox
# cannot reach 192.168.178.* — see ``feedback_sandbox_host_trennung.md``.
#
# Invocation
# ----------
#
#   sudo bash /opt/wakir-runtime/scripts/acceptance/wakir-pilot-acceptance.sh
#
# Or from an operator-host (Mira-Hand) over SSH:
#
#   ssh operator@<pilot-vm-ip> \
#     'sudo bash /opt/wakir-runtime/scripts/acceptance/wakir-pilot-acceptance.sh'
#
# Env-Vars (all optional, defaults below)
# ---------------------------------------
#
#   WAKIR_PILOT_MODE          default: federation
#                             {federation, single-org}
#   WAKIR_SIDE                default: orbit  (federation-mode)
#   WAKIR_PEER_SIDE           default: wakir  (federation-mode)
#   WAKIR_PEER_HOST           default: 192.168.178.116
#   WAKIR_SKIP_COSIGN_VERIFY  default: 1  (DEV-ONLY)
#   WAKIR_REPO_ROOT           default: /opt/wakir-runtime
#
# Exit-Codes
# ----------
#
#   0  Acceptance PASS
#   1  Pre-Flight-Fehler
#   2  Bootstrap-Phase-Fehler
#   3  Acceptance-Verifikation fehlgeschlagen
#
# -- Tomás

set -eu -o pipefail

WAKIR_PILOT_MODE="${WAKIR_PILOT_MODE:-federation}"
WAKIR_SIDE="${WAKIR_SIDE:-orbit}"
WAKIR_PEER_SIDE="${WAKIR_PEER_SIDE:-wakir}"
WAKIR_PEER_HOST="${WAKIR_PEER_HOST:-192.168.178.116}"
WAKIR_SKIP_COSIGN_VERIFY="${WAKIR_SKIP_COSIGN_VERIFY:-1}"
WAKIR_REPO_ROOT="${WAKIR_REPO_ROOT:-/opt/wakir-runtime}"

log()  { printf '[wakir-pilot-acceptance] %s\n' "$*"; }
warn() { printf '[wakir-pilot-acceptance] WARN: %s\n' "$*" >&2; }
fail() { printf '[wakir-pilot-acceptance] FAIL: %s\n' "$*" >&2; exit "${2:-1}"; }

# --- Pre-flight ------------------------------------------------------------

if [[ "$(id -u)" != "0" ]]; then
  fail "must run as root (sudo bash $0)" 1
fi

if [[ ! -d "$WAKIR_REPO_ROOT" ]]; then
  fail "repo root not found at $WAKIR_REPO_ROOT — install wakir-runtime first" 1
fi

# --- Dispatch --------------------------------------------------------------

case "$WAKIR_PILOT_MODE" in
  federation)
    fed_script="${WAKIR_REPO_ROOT}/scripts/federation-live-vm-acceptance.sh"
    if [[ ! -f "$fed_script" ]]; then
      fail "federation acceptance script not found at $fed_script" 1
    fi
    log "dispatching to federation acceptance lane (side=${WAKIR_SIDE} peer=${WAKIR_PEER_SIDE})"
    exec env \
      WAKIR_SIDE="$WAKIR_SIDE" \
      WAKIR_PEER_SIDE="$WAKIR_PEER_SIDE" \
      WAKIR_PEER_HOST="$WAKIR_PEER_HOST" \
      WAKIR_PILOT_MODE="$WAKIR_PILOT_MODE" \
      WAKIR_SKIP_COSIGN_VERIFY="$WAKIR_SKIP_COSIGN_VERIFY" \
      WAKIR_REPO_ROOT="$WAKIR_REPO_ROOT" \
      bash "$fed_script"
    ;;
  single-org)
    log "running single-org acceptance probe inline"
    bootstrap="${WAKIR_REPO_ROOT}/infra/spire/federation/wakir-pilot-bootstrap.sh"
    if [[ ! -f "$bootstrap" ]]; then
      fail "bootstrap script not found at $bootstrap" 1
    fi
    if ! command -v podman >/dev/null 2>&1; then
      fail "podman not installed" 1
    fi

    # Phase 1: bootstrap-re-run (single-org mode).
    log "Phase 1: bootstrap-re-run (single-org mode)"
    bootstrap_log="$(mktemp -t wakir-pilot-acceptance.XXXXXX.log)"
    log "bootstrap log: $bootstrap_log"
    set +e
    WAKIR_PILOT_MODE="single-org" \
    WAKIR_SKIP_COSIGN_VERIFY="$WAKIR_SKIP_COSIGN_VERIFY" \
    WAKIR_SKIP_PROMPTS=1 \
      bash "$bootstrap" >"$bootstrap_log" 2>&1
    rc=$?
    set -e
    if [[ $rc -ne 0 ]]; then
      warn "bootstrap exited with rc=$rc"
      tail -50 "$bootstrap_log" >&2
      fail "Phase 1 (bootstrap-re-run) failed — see $bootstrap_log" 2
    fi
    log "Phase 1: PASS"

    # Phase 2: single-org unit probes. In single-org mode the units
    # are the bare names (no side-suffix, no -federation- substring).
    log "Phase 2: single-org SPIRE unit probes"
    for unit in wakir-spire-server.service wakir-spire-agent.service; do
      if ! systemctl is-active --quiet "$unit"; then
        systemctl status "$unit" >&2 || true
        fail "$unit is not active" 3
      fi
      log "  - ${unit}: active"
    done

    # Phase 3: smoke (single-org, no peer-side).
    log "Phase 3: single-org smoke-test"
    smoke_log="$(mktemp -t wakir-pilot-acceptance-smoke.XXXXXX.log)"
    set +e
    sudo -u wakir \
      "${WAKIR_REPO_ROOT}/bin/proxmox-bringup-smoke" \
        --org acme \
        --side single \
      >"$smoke_log" 2>&1
    rc=$?
    set -e
    if [[ $rc -ne 0 ]]; then
      tail -50 "$smoke_log" >&2
      fail "single-org smoke-test failed (rc=$rc) — see $smoke_log" 3
    fi
    log "Phase 3: PASS"

    log ""
    log "Single-Org Live-VM Acceptance: PASS"
    log "  bootstrap: $bootstrap_log"
    log "  smoke:     $smoke_log"
    exit 0
    ;;
  *)
    fail "unknown WAKIR_PILOT_MODE='$WAKIR_PILOT_MODE' (expected: federation, single-org)" 1
    ;;
esac
