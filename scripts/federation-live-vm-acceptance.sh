#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Federation Live-VM Acceptance Lane.
# Bug-38 substance-fix applied (service-naming +
# smoke-fed-gate activation).
#
# **Why this script exists.**
#
# Bug-30..33 (HCL-named-block, profile-field, federates_with-
# placement, bootstrap-skip-cosign-resolver) made it past the hermetic
# Sandbox test surface and only surfaced during M-3 Live-Trial on
# wakir-orbit. Memory anchor `feedback_live_bringup_sandbox_gap.md`
# triggered for the 6th time that day; this script is the canonical
# Live-VM-Acceptance lane that closes the gap from the **operator-side**
# in addition to the hermetic HCL-shape test surface in
# tests/infra/test_federation_config_hcl_shape.py (
# T-FED-HCL-01..08).
#
# Sandbox boundary
# ----------------
#
# This script DOES NOT run in the claude-dev Sandbox. It runs on an
# operator-controlled host (operator-hand) that has SSH access to the
# Pilot-VM. The Sandbox cannot reach the operator LAN at all — that is
# the host-operations boundary documented in the operations docs.
#
# CI integration
# --------------
#
# This script is the "Live-VM acceptance" lane that ADR-0060 was meant
# to formalise but was rejected on cost grounds; the
# no-cost alternative (Quadlet-lint + SELinux-hermetic + this Live-VM script
# triggered by hand when a substrate change lands) covers the same gap.
# When a new federation-substrate PR lands on main, the operator runs this
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
# Or from an operator-host (operator-hand) over SSH:
#
#   ssh operator@<pilot-vm-ip> \
#     'sudo bash /opt/wakir-runtime/scripts/federation-live-vm-acceptance.sh'
#
# Env-Vars (all optional, defaults below)
# ---------------------------------------
#
#   WAKIR_SIDE                default: orbit
#   WAKIR_PEER_SIDE           default: wakir
#   WAKIR_PEER_HOST           REQUIRED, no default. The peer VM's
#                             address on the operator network, e.g.
#                             192.0.2.116 (RFC 5737 documentation
#                             range; substitute the real one).
#   WAKIR_PILOT_MODE          default: federation
#   WAKIR_SKIP_COSIGN_VERIFY  default: 1  (DEV-ONLY, parity with the
# M-3 Live-Trial topology)
#   WAKIR_REPO_ROOT           default: /opt/wakir-runtime
#   WAKIR_REPO_REF_MODE       default: track-remote
#   WAKIR_REPO_REF            default: (unset)
#
# Which tree this lane measures
# -----------------------------
#
# Until 2026-09-22 the answer was always ``origin/main``, whatever was
# on the node: the bootstrap's step 4 ended with
# ``reset --hard origin/<branch>`` unconditionally, so a change placed
# on the node was gone before the steps under test ran. The only lane
# this house has for live evidence could measure only what was already
# merged, which put the order the wrong way round -- believe, merge,
# then measure.
#
# ``WAKIR_REPO_REF_MODE`` now selects what step 4 does:
#
#   track-remote  (default) fetch and reset to the canonical branch tip.
#   pin           check out ``WAKIR_REPO_REF``, e.g. refs/pull/<n>/head,
#                 to measure a change before it is merged.
#   keep          leave the checkout exactly as it is.
#
# Whatever the mode, step 4 measures the resulting tree and writes a
# provenance record, and this script reads it back and prints which tree
# the run used -- in the summary and on every failure path. If the tree
# is not the canonical branch tip, or cannot be established, the run
# finishes with ``NOT EVIDENCE`` and exit 10 instead of ``PASS``, and
# the regression list is not printed. A report you cannot tell apart
# from a canonical one is worse than the old state, because in the old
# state you at least knew it was always ``main``.
#
# Exit-Codes
# ----------
#
#   0  Acceptance PASS — bootstrap-re-run finished cleanly without
# operator-hand Patches, federation-mode active on the VM, and the run
#      used the canonical branch tip.
#   1  Pre-Flight-Fehler (script not on the Pilot-VM, repo missing, ...)
#   2  Bootstrap-Phase-Fehler (a step failed; check the bootstrap log)
#   3  Acceptance-Verifikation fehlgeschlagen (bootstrap succeeded but
#      a smoke-check did not).
#  10  Every check passed, but NOT against the canonical tree, or the
#      tree could not be established. Not a failure and not evidence —
#      a third outcome on purpose, so that no caller can read it as
#      either of the other two.
#
# -- dev-engineering

set -eu -o pipefail

WAKIR_SIDE="${WAKIR_SIDE:-orbit}"
WAKIR_PEER_SIDE="${WAKIR_PEER_SIDE:-wakir}"
# No default: see the note in scripts/acceptance/wakir-pilot-acceptance.sh.
# The pre-flight below aborts with the variable name when it is unset,
# rather than silently probing whatever host used to be the default.
WAKIR_PEER_HOST="${WAKIR_PEER_HOST:-}"
WAKIR_PILOT_MODE="${WAKIR_PILOT_MODE:-federation}"
WAKIR_SKIP_COSIGN_VERIFY="${WAKIR_SKIP_COSIGN_VERIFY:-1}"
WAKIR_REPO_ROOT="${WAKIR_REPO_ROOT:-/opt/wakir-runtime}"
WAKIR_REPO_REF_MODE="${WAKIR_REPO_REF_MODE:-track-remote}"
WAKIR_REPO_REF="${WAKIR_REPO_REF:-}"

log()  { printf '[fed-live-vm-acceptance] %s\n' "$*"; }
warn() { printf '[fed-live-vm-acceptance] WARN: %s\n' "$*" >&2; }
fail() { printf '[fed-live-vm-acceptance] FAIL: %s\n' "$*" >&2; exit "${2:-1}"; }

# --- Pre-flight ------------------------------------------------------------

if [[ -z "$WAKIR_PEER_HOST" ]]; then
  fail "WAKIR_PEER_HOST is not set, and this script federates against a peer VM.
  Set it to the peer VM's address on your operator network and re-run, e.g.

      WAKIR_PEER_HOST=<peer-vm-address> sudo -E bash $0"
fi

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

provenance_lib="${WAKIR_REPO_ROOT}/scripts/lib/repo-provenance.sh"
if [[ ! -f "$provenance_lib" ]]; then
  fail "provenance reader not found at $provenance_lib — this checkout predates the tree-provenance record, and a run from it cannot say which tree it measured" 1
fi
# shellcheck source=scripts/lib/repo-provenance.sh
source "$provenance_lib"

# The nonce the bootstrap writes into its record and this script
# requires back. Without it a record left behind by an earlier run would
# be read as a statement about this one.
provenance_run_id="$(wakir_provenance_new_run_id)"

log "side=${WAKIR_SIDE} peer=${WAKIR_PEER_SIDE}@${WAKIR_PEER_HOST} mode=${WAKIR_PILOT_MODE} skip_cosign=${WAKIR_SKIP_COSIGN_VERIFY} ref_mode=${WAKIR_REPO_REF_MODE}${WAKIR_REPO_REF:+ ref=${WAKIR_REPO_REF}}"

# --- Phase 1: bootstrap-re-run ---------------------------------------------

log "Phase 1: invoking wakir-pilot-bootstrap.sh (Bug-30..33 acceptance)"
bootstrap_log="$(mktemp -t fed-live-vm-acceptance.XXXXXX.log)"
log "bootstrap log: $bootstrap_log"

set +e
WAKIR_PILOT_MODE="$WAKIR_PILOT_MODE" \
WAKIR_SIDE="$WAKIR_SIDE" \
WAKIR_PEER_SIDE="$WAKIR_PEER_SIDE" \
WAKIR_PEER_HOST="$WAKIR_PEER_HOST" \
WAKIR_SKIP_COSIGN_VERIFY="$WAKIR_SKIP_COSIGN_VERIFY" \
WAKIR_REPO_ROOT="$WAKIR_REPO_ROOT" \
WAKIR_REPO_REF_MODE="$WAKIR_REPO_REF_MODE" \
WAKIR_REPO_REF="$WAKIR_REPO_REF" \
WAKIR_PROVENANCE_RUN_ID="$provenance_run_id" \
WAKIR_SKIP_PROMPTS=1 \
  bash "$bootstrap" >"$bootstrap_log" 2>&1
rc=$?
set -e

# Read the tree back BEFORE the rc is handled, so that the failure paths
# below name the tree too. A failing run whose tree is unknown has
# wasted the operator's time twice over.
set +e
wakir_provenance_load "$provenance_run_id"
set -e
log "$(wakir_provenance_tree_line)"

if [[ $rc -ne 0 ]]; then
  warn "bootstrap exited with rc=$rc"
  tail -50 "$bootstrap_log" >&2
  fail "Phase 1 (bootstrap-re-run) failed — see $bootstrap_log for full output" 2
fi
log "Phase 1: bootstrap-re-run PASS"

# --- Phase 2: SPIRE-Server federation-mode verification --------------------

log "Phase 2: verifying SPIRE-Server federation-mode active"

# Bug-38 substance-fix: in federation-mode the Quadlet
# unit names are side-suffixed (one SPIRE-Server-federation per side).
# The acceptance script hard-coded the single-org base names
# ``wakir-spire-server.service`` / ``wakir-spire-agent.service``, which
# do not exist in federation-mode. The smoke CLI already uses the
# side-suffixed shape (bin/proxmox-bringup-smoke L325/326), so this
# script aligns with that convention:
#
#   server: wakir-spire-server-federation-${WAKIR_SIDE}.service
#   agent:  wakir-spire-agent-${WAKIR_SIDE}.service
#
# WAKIR_SIDE defaults to "orbit" at the top of this file; the operator
# overrides via env-var for the wakir-side run.

server_unit="wakir-spire-server-federation-${WAKIR_SIDE}.service"
agent_unit="wakir-spire-agent-${WAKIR_SIDE}.service"

# (a) Quadlet server-unit is loaded + active.
if ! systemctl is-active --quiet "$server_unit"; then
  systemctl status "$server_unit" >&2 || true
  fail "$server_unit is not active" 3
fi
log "  - ${server_unit}: active"

# (b) Quadlet agent-unit is loaded + active (Bug-37 substance acceptance:
#     the agent must not restart-loop on join-token misconfiguration).
if ! systemctl is-active --quiet "$agent_unit"; then
  systemctl status "$agent_unit" >&2 || true
  fail "$agent_unit is not active" 3
fi
log "  - ${agent_unit}: active"

# (c) Bundle-endpoint listener bound on 0.0.0.0:8443 (federation-mode
#     requires cross-VM reachability, not loopback).
if ! ss -tnlp 2>/dev/null | grep -q ':8443'; then
  ss -tnlp >&2 || true
  fail "bundle-endpoint listener not bound on :8443 — federation-mode requires the listener" 3
fi
log "  - bundle-endpoint listener: bound on :8443"

# (d) SPIRE-Server log shows no `malformed configuration` error
# (Bug-30/31/32 surfaced as that exact error string M-3
#     Live-Trial).
if journalctl -u "$server_unit" --since '5 minutes ago' 2>/dev/null \
   | grep -qi 'malformed configuration'; then
  journalctl -u "$server_unit" --since '5 minutes ago' | tail -30 >&2
  fail "SPIRE-Server log contains 'malformed configuration' — Bug-30/31/32 regression" 3
fi
log "  - SPIRE-Server log: no 'malformed configuration' (Bug-30..32 clean)"

# (e) federates_with peer reachable on TCP 8443 (the cross-VM
#     reachability part — does NOT validate the SPIFFE handshake, just
#     that the peer is up. Full bundle-fetch handshake is verified by
#     the smoke-test below).
if ! timeout 5 bash -c "exec 3<>/dev/tcp/${WAKIR_PEER_HOST}/8443" 2>/dev/null; then
  warn "peer ${WAKIR_PEER_HOST}:8443 not reachable — this is expected if the peer-VM is offline; federation-mode on this side is still verified."
else
  log "  - peer ${WAKIR_PEER_HOST}:8443: TCP reachable"
fi

# --- Phase 3: smoke-test ---------------------------------------------------

# Bug-38 substance-fix: activate the federation-bundle-
# sync + cross-trust-domain-verify checks. The smoke CLI gates them on
# WAKIR_FEDERATION_MODE=enabled AND --peer-side. The acceptance
# script set neither, so the two substance checks
# always SKIPped — which defeated the whole point of running the smoke
# inside a federation-mode acceptance lane. Pass both explicitly:
#
#   - WAKIR_FEDERATION_MODE=enabled  (env, gate for the two checks)
#   - --peer-side ${WAKIR_PEER_SIDE} (CLI, peer-side trust-domain)

log "Phase 3: running proxmox-bringup-smoke (federation-mode, peer-side=${WAKIR_PEER_SIDE})"
smoke_log="$(mktemp -t fed-live-vm-smoke.XXXXXX.log)"
set +e
sudo -u wakir \
  WAKIR_FEDERATION_MODE=enabled \
  "${WAKIR_REPO_ROOT}/bin/proxmox-bringup-smoke" \
    --org acme \
    --side "$WAKIR_SIDE" \
    --peer-side "$WAKIR_PEER_SIDE" \
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
if ! wakir_provenance_is_evidence; then
  # Every check above passed. They passed against a tree that is not the
  # canonical branch tip, or against one this run could not establish.
  # The regression list below is precisely what gets quoted afterwards,
  # so it is not printed: a list of bugs "regression-tested: clean"
  # against an unknown tree is a claim about nothing.
  log "Federation Live-VM Acceptance: NOT EVIDENCE"
  log "  side=${WAKIR_SIDE} peer=${WAKIR_PEER_SIDE}@${WAKIR_PEER_HOST}"
  log "  $(wakir_provenance_tree_line)"
  log ""
  log "  Every check in this run passed. The run is still not acceptance"
  log "  evidence, because it did not measure the canonical tree. The"
  log "  regression list is deliberately omitted."
  log ""
  log "  For evidence, re-run with WAKIR_REPO_REF_MODE=track-remote"
  log "  (the default) once the change is on ${WAKIR_REPO_BRANCH:-main}."
  log ""
  log "Logs:"
  log "  bootstrap: $bootstrap_log"
  log "  smoke:     $smoke_log"
  exit "$WAKIR_PROVENANCE_NOT_EVIDENCE_RC"
fi

log "Federation Live-VM Acceptance: PASS"
log "  side=${WAKIR_SIDE} peer=${WAKIR_PEER_SIDE}@${WAKIR_PEER_HOST}"
log "  $(wakir_provenance_tree_line)"
log "  - bootstrap-re-run: clean, no Operator-Hand-Patches needed"
log "  - SPIRE-Server: federation-mode active, no 'malformed configuration'"
log "  - smoke-test: PASS"
log ""
log "Bug-30 (named-block-syntax) regression-tested: clean"
log "Bug-31 (profile-flat-attribute) regression-tested: clean"
log "Bug-32 (federates_with-placement) regression-tested: clean"
log "Bug-33 (bootstrap-skip-cosign-resolver) regression-tested: clean"
log "Bug-36 (resolver-skip-cosign-mode-lücke) regression-tested: clean"
log "Bug-37 (agent-join-token config-coherency) regression-tested: clean (agent unit active)"
log "Bug-38 (acceptance-script service-naming + smoke-fed-gate) regression-tested: clean"
log ""
log "Logs:"
log "  bootstrap: $bootstrap_log"
log "  smoke:     $smoke_log"
exit 0
