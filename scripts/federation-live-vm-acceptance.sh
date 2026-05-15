#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-10 Tag-6 — Federation Live-VM Acceptance Lane.
#
# **Why this script exists.**
#
# Sprint-10 Tag-5 Bug-30..33 (HCL-named-block, profile-field, federates_with-
# placement, bootstrap-skip-cosign-resolver) made it past the hermetic
# Sandbox test surface and only surfaced during M-3 Live-Trial on
# wakir-orbit. Memory anchor `feedback_live_bringup_sandbox_gap.md`
# triggered for the 6th time that day; this script is the canonical
# Live-VM-Acceptance lane that closes the gap from the **operator-side**
# in addition to the hermetic HCL-shape test surface in
# tests/infra/test_federation_config_hcl_shape.py (Sprint-10 Tag-6,
# T-FED-HCL-01..08).
#
# Sandbox boundary
# ----------------
#
# This script DOES NOT run in the claude-dev Sandbox. It runs on an
# operator-controlled host (Mira-Hand) that has SSH access to the
# Pilot-VM. The Sandbox cannot reach 192.168.178.* — that is the host-
# operations boundary documented by `feedback_sandbox_host_trennung.md`.
#
# CI integration
# --------------
#
# This script is the "Live-VM acceptance" lane that ADR-0060 was meant
# to formalise but was rejected on cost grounds; the kostenfreie
# alternative (Quadlet-Lint + SELinux-Hermetic + this Live-VM script
# triggered by-hand on Sprint-Substrate-Closers) covers the same gap.
# When a new federation-substrate PR lands on main, Mira runs this
# script against wakir-orbit (or wakir-pilot) before the next
# Migrations-Pilot phase-gate.
#
# Invocation
# ----------
#
# Run on the Pilot-VM as root, AFTER the substrate is installed at
# /opt/wakir-runtime (so the script can resolve the bootstrap path):
#
#   sudo bash /opt/wakir-runtime/scripts/federation-live-vm-acceptance.sh
#
# Or from an operator-host (Mira-Hand) over SSH:
#
#   ssh operator@<pilot-vm-ip> \
#     'sudo bash /opt/wakir-runtime/scripts/federation-live-vm-acceptance.sh'
#
# Env-Vars (all optional, defaults below)
# ---------------------------------------
#
#   WAKIR_SIDE                default: orbit
#   WAKIR_PEER_SIDE           default: wakir
#   WAKIR_PEER_HOST           default: 192.168.178.116
#   WAKIR_PILOT_MODE          default: federation
#   WAKIR_SKIP_COSIGN_VERIFY  default: 1  (DEV-ONLY, parity with the
#                             Sprint-10 Tag-5 M-3 Live-Trial topology)
#   WAKIR_REPO_ROOT           default: /opt/wakir-runtime
#
# Exit-Codes
# ----------
#
#   0  Acceptance PASS — bootstrap-re-run finished cleanly without
#      Mira-Hand-Patches, federation-mode active on the VM.
#   1  Pre-Flight-Fehler (script not on the Pilot-VM, repo missing, ...)
#   2  Bootstrap-Phase-Fehler (a step failed; check the bootstrap log)
#   3  Acceptance-Verifikation fehlgeschlagen (bootstrap succeeded but
#      a smoke-check did not).
#
# -- Tomás

set -eu -o pipefail

WAKIR_SIDE="${WAKIR_SIDE:-orbit}"
WAKIR_PEER_SIDE="${WAKIR_PEER_SIDE:-wakir}"
WAKIR_PEER_HOST="${WAKIR_PEER_HOST:-192.168.178.116}"
WAKIR_PILOT_MODE="${WAKIR_PILOT_MODE:-federation}"
WAKIR_SKIP_COSIGN_VERIFY="${WAKIR_SKIP_COSIGN_VERIFY:-1}"
WAKIR_REPO_ROOT="${WAKIR_REPO_ROOT:-/opt/wakir-runtime}"

log()  { printf '[fed-live-vm-acceptance] %s\n' "$*"; }
warn() { printf '[fed-live-vm-acceptance] WARN: %s\n' "$*" >&2; }
fail() { printf '[fed-live-vm-acceptance] FAIL: %s\n' "$*" >&2; exit "${2:-1}"; }

# --- Pre-flight ------------------------------------------------------------

bootstrap="${WAKIR_REPO_ROOT}/infra/spire/federation/wakir-pilot-bootstrap.sh"
if [[ ! -f "$bootstrap" ]]; then
  fail "bootstrap script not found at $bootstrap — install the wakir-runtime repo first (git clone https://github.com/wakir-labs/wakir-runtime ${WAKIR_REPO_ROOT})" 1
fi

if [[ "$(id -u)" != "0" ]]; then
  fail "must run as root (sudo bash $0)" 1
fi

if ! command -v podman >/dev/null 2>&1; then
  fail "podman not installed — the bootstrap script needs it for Quadlet" 1
fi

log "side=${WAKIR_SIDE} peer=${WAKIR_PEER_SIDE}@${WAKIR_PEER_HOST} mode=${WAKIR_PILOT_MODE} skip_cosign=${WAKIR_SKIP_COSIGN_VERIFY}"

# --- Phase 1: bootstrap-re-run ---------------------------------------------

log "Phase 1: invoking wakir-pilot-bootstrap.sh (Sprint-10 Tag-5 Bug-30..33 acceptance)"
bootstrap_log="$(mktemp -t fed-live-vm-acceptance.XXXXXX.log)"
log "bootstrap log: $bootstrap_log"

set +e
WAKIR_PILOT_MODE="$WAKIR_PILOT_MODE" \
WAKIR_SIDE="$WAKIR_SIDE" \
WAKIR_PEER_SIDE="$WAKIR_PEER_SIDE" \
WAKIR_PEER_HOST="$WAKIR_PEER_HOST" \
WAKIR_SKIP_COSIGN_VERIFY="$WAKIR_SKIP_COSIGN_VERIFY" \
WAKIR_SKIP_PROMPTS=1 \
  bash "$bootstrap" >"$bootstrap_log" 2>&1
rc=$?
set -e

if [[ $rc -ne 0 ]]; then
  warn "bootstrap exited with rc=$rc"
  tail -50 "$bootstrap_log" >&2
  fail "Phase 1 (bootstrap-re-run) failed — see $bootstrap_log for full output" 2
fi
log "Phase 1: bootstrap-re-run PASS"

# --- Phase 2: SPIRE-Server federation-mode verification --------------------

log "Phase 2: verifying SPIRE-Server federation-mode active"

# (a) Quadlet unit is loaded + active.
if ! systemctl is-active --quiet wakir-spire-server.service; then
  systemctl status wakir-spire-server.service >&2 || true
  fail "wakir-spire-server.service is not active" 3
fi
log "  - wakir-spire-server.service: active"

# (b) Bundle-endpoint listener bound on 0.0.0.0:8443 (federation-mode
#     requires cross-VM reachability, not loopback).
if ! ss -tnlp 2>/dev/null | grep -q ':8443'; then
  ss -tnlp >&2 || true
  fail "bundle-endpoint listener not bound on :8443 — federation-mode requires the listener" 3
fi
log "  - bundle-endpoint listener: bound on :8443"

# (c) SPIRE-Server log shows no `malformed configuration` error
#     (Bug-30/31/32 surfaced as that exact error string in Tag-5 M-3
#     Live-Trial).
if journalctl -u wakir-spire-server.service --since '5 minutes ago' 2>/dev/null \
   | grep -qi 'malformed configuration'; then
  journalctl -u wakir-spire-server.service --since '5 minutes ago' | tail -30 >&2
  fail "SPIRE-Server log contains 'malformed configuration' — Bug-30/31/32 regression" 3
fi
log "  - SPIRE-Server log: no 'malformed configuration' (Bug-30..32 clean)"

# (d) federates_with peer reachable on TCP 8443 (the cross-VM
#     reachability part — does NOT validate the SPIFFE handshake, just
#     that the peer is up. Full bundle-fetch handshake is verified by
#     the smoke-test below).
if ! timeout 5 bash -c "exec 3<>/dev/tcp/${WAKIR_PEER_HOST}/8443" 2>/dev/null; then
  warn "peer ${WAKIR_PEER_HOST}:8443 not reachable — this is expected if the peer-VM is offline; federation-mode on this side is still verified."
else
  log "  - peer ${WAKIR_PEER_HOST}:8443: TCP reachable"
fi

# --- Phase 3: smoke-test ---------------------------------------------------

log "Phase 3: running proxmox-bringup-smoke (federation-mode)"
smoke_log="$(mktemp -t fed-live-vm-smoke.XXXXXX.log)"
set +e
sudo -u wakir "${WAKIR_REPO_ROOT}/bin/proxmox-bringup-smoke" \
  --org acme \
  --side "$WAKIR_SIDE" \
  >"$smoke_log" 2>&1
rc=$?
set -e

if [[ $rc -ne 0 ]]; then
  tail -50 "$smoke_log" >&2
  fail "proxmox-bringup-smoke failed (rc=$rc) — see $smoke_log" 3
fi
log "Phase 3: smoke-test PASS"

# --- Acceptance summary ----------------------------------------------------

log ""
log "Federation Live-VM Acceptance: PASS"
log "  side=${WAKIR_SIDE} peer=${WAKIR_PEER_SIDE}@${WAKIR_PEER_HOST}"
log "  - bootstrap-re-run: clean, no Operator-Hand-Patches needed"
log "  - SPIRE-Server: federation-mode active, no 'malformed configuration'"
log "  - smoke-test: PASS"
log ""
log "Bug-30 (named-block-syntax) regression-tested: clean"
log "Bug-31 (profile-flat-attribute) regression-tested: clean"
log "Bug-32 (federates_with-placement) regression-tested: clean"
log "Bug-33 (bootstrap-skip-cosign-resolver) regression-tested: clean"
log ""
log "Logs:"
log "  bootstrap: $bootstrap_log"
log "  smoke:     $smoke_log"
exit 0
