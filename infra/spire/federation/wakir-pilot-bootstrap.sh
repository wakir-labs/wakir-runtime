#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# One-Shot Wakir-Pilot-VM Bring-up.
#
# Companion zum (laengeren) PROXMOX_BRING_UP_RECIPE.md. Wo der Recipe-
# Text dem Operator jeden Schritt einzeln zeigt, fasst dieses Skript
# alle Schritte zu einem einzigen Bring-up zusammen. Idempotent;
# Re-Run ist sicher.
#
# Aufruf:
#   curl -sSL https://raw.githubusercontent.com/wakir-labs/wakir-runtime/main/infra/spire/federation/wakir-pilot-bootstrap.sh | sudo bash
#   # oder:
#   sudo bash /opt/wakir-runtime/infra/spire/federation/wakir-pilot-bootstrap.sh
#   # oder Resume:
#   sudo bash wakir-pilot-bootstrap.sh --resume-from 5
#
# Env-Vars:
#   WAKIR_ORG_ID              default: acme
#   WAKIR_TRUST_DOMAIN        default: wakir.test (auto-syncs with
#                             WAKIR_SIDE when SIDE != wakir and the
#                             operator did not override; Cross-VM-
#                             Federation substance)
#   WAKIR_SIDE                default: wakir  (alt: orbit, partner;
# substance — selects
#                             which Quadlet-instance + config-pair
#                             the bootstrap installs. ``orbit`` is
#                             the Cross-VM Federation peer-VM.)
#   WAKIR_PILOT_MODE          default: single-org (
#                             Bug 7 substance-fix: choose between
#                             ``single-org`` Phase-1b pilot config
#                             variants and ``federation`` dual-side
#                             Phase-2.1 variants. Single-org is the
#                             default — Phase-1b pilot does not have
#                             a federation peer; using the federation
#                             configs in single-org mode crashes the
#                             SPIRE-Server on partner-peer-DNS-miss.
# substance: federation
#                             mode now wires <HOST_BUNDLE_BIND>=0.0.0.0
#                             so the bundle-endpoint is reachable
#                             cross-VM. Single-org keeps the bundle-
#                             endpoint loopback-only.)
#   WAKIR_PEER_SIDE default: (unset) —.
#                             Federation-mode only. Peer trust-domain
#                             side literal (e.g. ``wakir`` on the
#                             orbit-VM; ``orbit`` on the wakir-VM).
#                             Mirror of --peer-side in proxmox-
#                             bringup-smoke. When set together with
#                             WAKIR_PEER_HOST, the bootstrap installs
#                             an /etc/hosts entry mapping
#                             ``spire-server-<peer_side>`` to the
#                             peer VM's IP. Unset means Operator-Hand
#                             /etc/hosts setup (manual).
#   WAKIR_PEER_HOST default: (unset) —.
#                             Federation-mode only. Peer VM's IP for
#                             the /etc/hosts auto-install. For the
#                             home-LAN dogfood topology this is the
#                             peer VM's LAN IP (e.g. ``192.0.2.116``).
#                             For the Proxmox-internal bridge topology
#                             this is the bridge-internal IP (e.g.
#                             ``198.51.100.10``). Both examples are RFC
#                             5737 documentation addresses — substitute
#                             the real one for your topology.
#   WAKIR_REPO_BRANCH         default: main
#   WAKIR_REPO_URL            default: https://github.com/wakir-labs/wakir-runtime.git
#   WAKIR_REPO_ROOT           default: /opt/wakir-runtime
#   WAKIR_REPO_REF_MODE       default: track-remote
#                             What step 4 does to the checkout on the
#                             node:
#                               track-remote  fetch origin/<branch> and
#                                     reset --hard to it. The canonical
#                                     path and the default.
#                               pin   fetch WAKIR_REPO_REF and check the
#                                     checkout out at it, detached. For
#                                     measuring a change on the node
#                                     BEFORE it is merged.
#                               keep  leave the checkout exactly as it
#                                     is. For measuring something that
#                                     was placed on the node by hand.
#                             Whatever the mode, step 4 measures the
#                             resulting tree and writes a provenance
#                             record; a run against a tree that is not
#                             the canonical branch tip is not acceptance
#                             evidence and the acceptance lanes refuse
#                             to report it as such.
#   WAKIR_REPO_REF            default: (unset) -- required by, and only
#                             accepted in, WAKIR_REPO_REF_MODE=pin. Any
#                             ref the remote will serve: a branch name,
#                             a tag, refs/pull/<n>/head.
#   WAKIR_REPO_PROVENANCE_FILE
#                             default: /var/lib/wakir/bootstrap/repo-provenance.env
#                             Where step 4 records which tree the run is
#                             about to use. Read back by the acceptance
#                             lanes through scripts/lib/repo-provenance.sh.
#   WAKIR_PROVENANCE_RUN_ID   default: (unset) -- a nonce the caller
#                             passes in and finds again in the record,
#                             so a leftover record from an earlier run
#                             cannot be mistaken for this one's.
#   WAKIR_SKIP_COSIGN_VERIFY  default: 0  (set to 1 for quick-pilot,
#                             container pulls run against tag-only,
#                             no digest pin -- DEV-ONLY)
#   WAKIR_SKIP_PROMPTS        default: 0  (set to 1 to take all
#                             interactive default answers -- needed
#                             for the hermetic test surface)
#   COSIGN_VERSION            default: v2.4.1
#
# Sandbox-Grenze: dieses Skript laeuft AUF DER VM (Operator-Hand-
# Pfad), nicht in der claude-dev-Sandbox. Es darf gegen ghcr.io,
# docker.io und github.com Egress haben. Hermetic-Tests in
# tests/infra/test_pilot_bootstrap.py mocken alle externen Calls.
#
# Exit-Codes:
#   0  Bring-up vollstaendig (oder Resume erfolgreich)
#   1  Argument-Fehler / Pre-Flight-Fehler
#   2  Mid-Phase-Fehler (Operator-Hand-Hinweis im Output)
#   3  CoreOS-Live-Modus erkannt (Hinweis: coreos-installer)
#
# Schritte (1..8):
#   1  Pre-Flight-Check (CoreOS-Detection, Podman, Network)
#   2  Toolbox-Container 'wakir-bringup' anlegen (CoreOS-rpm-ostree)
#   3  CLI-Tools installieren (cosign, skopeo, jq, git)
#   4  Repo klonen nach ${WAKIR_REPO_ROOT}
#   5  Image-Pin-Resolve via cosign + skopeo (3 Images)
#   6  Quadlet-Units installieren (Networks, Volumes, Server, Agent, NATS)
#   7  NATS-KV-Bucket-Init fuer Pilot-Org
#   8  Smoke-Test (proxmox-bringup-smoke --org $WAKIR_ORG_ID)
#

set -u

# ---------------------------------------------------------------------------
# Configuration / defaults
# ---------------------------------------------------------------------------

PROG=$(basename "$0")
TOTAL_STEPS=8
RESUME_FROM=1

# Resolve a stable script reference for resume hints. When the bootstrap
# is invoked via `curl ... | sudo bash`, $0 collapses to ``bash`` and a
# naive ${PROG} reference would print `sudo bash bash --resume-from N`
# (Bug 1). After step 4 the repo is on disk at
# ${WAKIR_REPO_ROOT}; prefer the installed path. Until then we fall back
# to a documented absolute path for a typical operator workflow.
_resume_cmd() {
  local step_n="$1"
  local installed="${WAKIR_REPO_ROOT}/infra/spire/federation/wakir-pilot-bootstrap.sh"
  if [[ -f "$installed" ]]; then
    printf 'sudo bash %s --resume-from %s' "$installed" "$step_n"
  elif [[ "$PROG" == "bash" ]] || [[ -z "$PROG" ]]; then
    # Piped-from-curl case before step 4: no on-disk script yet. Tell
    # the operator the canonical installed path explicitly.
    printf 'sudo bash %s --resume-from %s' "$installed" "$step_n"
  else
    printf 'sudo bash %s --resume-from %s' "$PROG" "$step_n"
  fi
}

: "${WAKIR_ORG_ID:=acme}"
: "${WAKIR_TRUST_DOMAIN:=wakir.test}"

# Cross-VM-Federation substance: the bootstrap is
# side-aware. ``WAKIR_SIDE`` selects which Quadlet-instance + which
# SPIRE-Server/Agent config-pair the bootstrap installs on this VM.
#
#   wakir   -> spire-server-wakir.conf + spire-agent-wakir.conf
#              (DEFAULT; the wakir-side Pilot-VM that has shipped
#              since the first bring-up)
#   orbit   -> spire-server-orbit.conf + spire-agent-orbit.conf
# (Cross-VM Federation peer-VM)
#
# The side literal is substituted into Quadlet ContainerName,
# NetworkAlias, volume basenames, and bind-mount paths via the
# existing ``<SIDE>`` placeholder mechanism (step_6_quadlet §6c+§6d).
# WAKIR_TRUST_DOMAIN auto-syncs with WAKIR_SIDE if not explicitly
# overridden by the operator — see the post-defaults block below.
: "${WAKIR_SIDE:=wakir}"
case "$WAKIR_SIDE" in
  wakir|orbit|partner) : ;;
  *)
    echo "[$PROG] ERROR: WAKIR_SIDE must be 'wakir', 'orbit', or 'partner'; got '${WAKIR_SIDE}'" >&2
    exit 1
    ;;
esac

# Auto-sync WAKIR_TRUST_DOMAIN with WAKIR_SIDE when the operator left
# WAKIR_TRUST_DOMAIN at the wakir.test default but selected a non-wakir
# side. If the operator explicitly set both, we trust the operator and
# do not second-guess.
if [[ "$WAKIR_SIDE" != "wakir" && "$WAKIR_TRUST_DOMAIN" == "wakir.test" ]]; then
  WAKIR_TRUST_DOMAIN="${WAKIR_SIDE}.test"
fi

: "${WAKIR_REPO_BRANCH:=main}"
: "${WAKIR_REPO_URL:=https://github.com/wakir-labs/wakir-runtime.git}"
: "${WAKIR_REPO_ROOT:=/opt/wakir-runtime}"

# Which tree step 4 leaves on the node, and how the run says so.
#
# Until this existed, step 4 always ended with
# ``reset --hard origin/<branch>``. That made the acceptance lane -- the
# only means this repository has of producing live evidence -- able to
# measure exactly one thing: what is already on the branch. A change
# could not be measured on the substrate before it was merged, so the
# order was: believe, merge, then measure. A run on 2026-09-22 spent
# twenty minutes producing no evidence in either direction for exactly
# this reason: the branch state that had been placed on the node was
# reset away by step 4 before the step under test ran.
#
# The default stays "fetch the canonical tree". The deviation is
# possible, has to be asked for, and -- this is the part that matters --
# is visible in the result: step 4 measures the tree it ends up with and
# records the measurement, and a lane that finds a non-canonical tree
# refuses to report its run as acceptance evidence.
: "${WAKIR_REPO_REF_MODE:=track-remote}"
case "$WAKIR_REPO_REF_MODE" in
  track-remote|pin|keep) : ;;
  *)
    echo "[$PROG] ERROR: WAKIR_REPO_REF_MODE must be 'track-remote', 'pin' or 'keep'; got '${WAKIR_REPO_REF_MODE}'" >&2
    exit 1
    ;;
esac
: "${WAKIR_REPO_REF:=}"
if [[ "$WAKIR_REPO_REF_MODE" == "pin" && -z "$WAKIR_REPO_REF" ]]; then
  echo "[$PROG] ERROR: WAKIR_REPO_REF_MODE=pin requires WAKIR_REPO_REF (a branch, tag or refs/pull/<n>/head)" >&2
  exit 1
fi
if [[ "$WAKIR_REPO_REF_MODE" != "pin" && -n "$WAKIR_REPO_REF" ]]; then
  # Silently ignoring it would mean the operator believes the run is
  # pinned while it is not. That is the failure mode this whole block
  # exists to remove, so it is an error rather than a warning.
  echo "[$PROG] ERROR: WAKIR_REPO_REF is set but WAKIR_REPO_REF_MODE is '${WAKIR_REPO_REF_MODE}'; the ref would be ignored" >&2
  exit 1
fi
if [[ -n "$WAKIR_REPO_REF" && "$WAKIR_REPO_REF" == -* ]]; then
  echo "[$PROG] ERROR: WAKIR_REPO_REF must not start with '-'; got '${WAKIR_REPO_REF}'" >&2
  exit 1
fi
: "${WAKIR_REPO_PROVENANCE_FILE:=/var/lib/wakir/bootstrap/repo-provenance.env}"
: "${WAKIR_PROVENANCE_RUN_ID:=}"
: "${WAKIR_SKIP_COSIGN_VERIFY:=0}"
: "${WAKIR_SKIP_PROMPTS:=0}"
: "${COSIGN_VERSION:=v2.4.1}"

# Bug-36-Härtung: explicit resolver trust-mode selector.
#
# Bug-36-Fix collapsed skip-cosign-mode into a
# skopeo-only-all-4 resolve path. That fix unblocked the Live-VM run
# at the cost of broadening the trust-base: SPIRE-server / SPIRE-
# agent / python pins are now resolved from repository-served
# manifests without Sigstore signature verification. For the Pilot-
# Phase this is acceptable (the Operator-Hand-run still inspects the
# digest; image-republish-drift is caught by the resolver's
# idempotency contract on re-run). For Production it is not.
#
# WAKIR_RESOLVER_TRUST_MODE makes the trust-base explicit:
#
#   cosign-strict   Default-PRODUCTION. Requires Sigstore-keyless
#                   verification for ghcr.io/spiffe/* and
#                   ghcr.io/wakir-labs/* images. SkopeoCross-check
#                   for digest agreement. python:3.13-slim is
#                   skopeo-only by upstream policy (DockerHub does
#                   not sign images). cosign-failure on any of the
#                   three signed images aborts step-5 with rc=2.
#
#   skopeo-only-all-4   Pilot-Phase-DEV. Resolves all 4 image pins
#                   via skopeo only. No Sigstore signature
#                   verification. Equivalent to the
#                   Bug-36-Fix path; this mode is the canonical
#                   spelling for the Bug-36-Fix behaviour and is
#                   what WAKIR_SKIP_COSIGN_VERIFY=1 maps to.
#
#   mixed           HYBRID. Cosign-verify where signing is available
#                   (ghcr.io/spiffe/*, ghcr.io/wakir-labs/*), skopeo-
#                   fallback only for the SPIRE-allowlist when the
#                   signature is temporarily unavailable (e.g.
#                   Sigstore-outage during a bring-up window). The
#                   allowlist is hard-coded — Operator-Hand cannot
#                   widen it without a source-patch. python:3.13-
#                   slim stays skopeo-only.
#
# Back-compat: WAKIR_SKIP_COSIGN_VERIFY=1 implies trust-mode
# "skopeo-only-all-4" when WAKIR_RESOLVER_TRUST_MODE is unset, so
# existing Live-VM-runbooks keep working byte-stable. Setting both
# to inconsistent values is an error.
#
# See framework/runtime/bootstrap/RESOLVER-TRUST-MODES.md for the
# threat-model + the Production-migration plan (cosign-strict
# becomes mandatory on Phase-3 cutover).
: "${WAKIR_RESOLVER_TRUST_MODE:=}"
case "$WAKIR_RESOLVER_TRUST_MODE" in
  ""|cosign-strict|skopeo-only-all-4|mixed) : ;;
  *)
    echo "[$PROG] ERROR: WAKIR_RESOLVER_TRUST_MODE must be 'cosign-strict', 'skopeo-only-all-4', or 'mixed'; got '${WAKIR_RESOLVER_TRUST_MODE}'" >&2
    exit 1
    ;;
esac
# Resolve the implicit/back-compat mapping. WAKIR_SKIP_COSIGN_VERIFY=1
# is the legacy spelling for skopeo-only-all-4. When the explicit
# trust-mode is also set, the two MUST agree (no silent override).
if [[ -z "$WAKIR_RESOLVER_TRUST_MODE" ]]; then
  if [[ "$WAKIR_SKIP_COSIGN_VERIFY" == "1" ]]; then
    WAKIR_RESOLVER_TRUST_MODE="skopeo-only-all-4"
  else
    WAKIR_RESOLVER_TRUST_MODE="cosign-strict"
  fi
else
  # Explicit trust-mode given; verify back-compat env-var is coherent.
  if [[ "$WAKIR_RESOLVER_TRUST_MODE" == "skopeo-only-all-4" \
        && "$WAKIR_SKIP_COSIGN_VERIFY" != "1" ]]; then
    # User asked for skopeo-only via the new var; accept and align the
    # legacy var so downstream branches keep working.
    WAKIR_SKIP_COSIGN_VERIFY=1
  elif [[ "$WAKIR_RESOLVER_TRUST_MODE" == "cosign-strict" \
          && "$WAKIR_SKIP_COSIGN_VERIFY" == "1" ]]; then
    echo "[$PROG] ERROR: WAKIR_RESOLVER_TRUST_MODE=cosign-strict conflicts with WAKIR_SKIP_COSIGN_VERIFY=1" >&2
    exit 1
  fi
fi

# Bug 7 substance-fix: single-org pilot mode toggles the
# SPIRE-Server + SPIRE-Agent config variants the bootstrap installs.
#
#   single-org   -> spire-server-pilot-single-org.conf
#                   spire-agent-pilot-single-org.conf
#                   (no federates_with, no bundle-endpoint listener,
#                    agent has insecure_bootstrap=true and no
#                    trust_bundle_path; agent template's federated-
#                    bundles read-only mount is dropped via in-place
#                    line-deletion).
#   federation   -> spire-server-${side}.conf
#                   spire-agent-${side}.conf
# (dual-side variants; requires
#                    BOTH wakir and partner sides to be installed on
#                    the SAME host to avoid the partner-peer-DNS-miss
#                    that crashes the server in Bug 7 H1).
#
# Phase-1b Pilot-VM bring-up defaults to ``single-org``. Phase-2.1
# dual-side bring-up sets WAKIR_PILOT_MODE=federation.
: "${WAKIR_PILOT_MODE:=single-org}"
case "$WAKIR_PILOT_MODE" in
  single-org|federation) : ;;
  *)
    echo "[$PROG] ERROR: WAKIR_PILOT_MODE must be 'single-org' or 'federation'; got '${WAKIR_PILOT_MODE}'" >&2
    exit 1
    ;;
esac

# substance-fix (M-3 Live-Trial): peer-host wiring for
# Cross-VM federation. When WAKIR_PILOT_MODE=federation, the bootstrap
# can OPTIONALLY install an /etc/hosts entry that maps the peer-side
# SPIRE-Server's DNS name (``spire-server-<peer_side>``) to the peer
# VM's IP. This automates step §5.2 of PARTNER_VM_BRING_UP_RECIPE.md
# (the Operator-Hand /etc/hosts edit). Both env-vars are required to
# trigger the auto-install; if either is empty, the bootstrap logs a
# note and leaves /etc/hosts untouched (Operator-Hand-fallback).
#
#   WAKIR_PEER_SIDE           e.g. ``wakir`` (peer trust-domain side
#                             literal; mirror of --peer-side in the
#                             proxmox-bringup-smoke script).
#   WAKIR_PEER_HOST           e.g. ``192.0.2.116`` (the peer VM's
#                             reachable IP — LAN-direct for the
#                             home-LAN dogfood topology, or the
#                             Proxmox-internal bridge IP).
#
# The bootstrap NEVER edits /etc/hosts in single-org mode (no peer
# exists). In federation mode without these vars, the operator MUST
# add the entry manually before federation-bundle-sync works.
: "${WAKIR_PEER_SIDE:=}"
: "${WAKIR_PEER_HOST:=}"

# Bug-39 Option-A substrate: bilateral-federation-handshake
# precheck gate. When set to "1", an OPTIONAL post-step (step_15) runs
# after step_8_smoke and verifies the prereqs for a bilateral mode-flip
# (peer-side in federation-mode + persona-container re-spawn-window
# declared). The precheck does NOT mutate the running VM; it produces a
# PASS/FAIL summary that the Operator-Hand uses as the go/no-go gate.
# Default 0 (no-op) so existing single-org + asymmetric-federation
# bring-ups remain byte-stable.
: "${WAKIR_BILATERAL_PRECHECK:=0}"
: "${WAKIR_PERSONA_RESPAWN_WINDOW:=}"
if [[ -n "$WAKIR_PEER_SIDE" ]] \
   && ! [[ "$WAKIR_PEER_SIDE" =~ ^[a-z][a-z0-9]*$ ]]; then
  echo "[$PROG] ERROR: WAKIR_PEER_SIDE must be lowercase ASCII + digits, starting with a letter; got '${WAKIR_PEER_SIDE}'" >&2
  exit 1
fi
if [[ -n "$WAKIR_PEER_HOST" ]] \
   && ! [[ "$WAKIR_PEER_HOST" =~ ^[0-9a-zA-Z.:_\-]+$ ]]; then
  echo "[$PROG] ERROR: WAKIR_PEER_HOST contains disallowed characters; got '${WAKIR_PEER_HOST}'" >&2
  exit 1
fi
if [[ -n "$WAKIR_PEER_SIDE" && "$WAKIR_PEER_SIDE" == "$WAKIR_SIDE" ]]; then
  echo "[$PROG] ERROR: WAKIR_PEER_SIDE ($WAKIR_PEER_SIDE) must differ from WAKIR_SIDE ($WAKIR_SIDE)" >&2
  exit 1
fi

# Test-injection hooks. In production these expand to nothing; the
# hermetic test surface in tests/infra/test_pilot_bootstrap.py can
# point these at fixtures.
: "${WAKIR_BOOTSTRAP_PODMAN:=podman}"
: "${WAKIR_BOOTSTRAP_SYSTEMCTL:=systemctl}"
: "${WAKIR_BOOTSTRAP_CURL:=curl}"
: "${WAKIR_BOOTSTRAP_GIT:=git}"
: "${WAKIR_BOOTSTRAP_SMOKE:=}"   # if empty, derived from REPO_ROOT
: "${WAKIR_BOOTSTRAP_TOOLBOX:=toolbox}"
: "${WAKIR_BOOTSTRAP_SLEEP:=sleep}"   # Bug-25 wait-helpers; tests inject noop

#: hermetic-friendly path for the /etc/hosts peer-host
# entry. Tests inject WAKIR_BOOTSTRAP_HOSTS=/path/to/fake-hosts so the
# bootstrap appends to the fixture, not to the system file.
: "${WAKIR_BOOTSTRAP_HOSTS:=/etc/hosts}"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

_RED=""
_GREEN=""
_YELLOW=""
_BOLD=""
_RESET=""
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1; then
  _RED=$(tput setaf 1 2>/dev/null || true)
  _GREEN=$(tput setaf 2 2>/dev/null || true)
  _YELLOW=$(tput setaf 3 2>/dev/null || true)
  _BOLD=$(tput bold 2>/dev/null || true)
  _RESET=$(tput sgr0 2>/dev/null || true)
fi

log_step() {
  local n="$1"
  local total="$2"
  local label="$3"
  printf '%s[%d/%d]%s %s ...\n' "$_BOLD" "$n" "$total" "$_RESET" "$label"
}
log_ok()    { printf '      %sOK%s    %s\n' "$_GREEN" "$_RESET" "$1"; }
log_warn()  { printf '      %sWARN%s  %s\n' "$_YELLOW" "$_RESET" "$1"; }
log_err()   { printf '      %sERROR%s %s\n' "$_RED" "$_RESET" "$1" >&2; }
log_note()  { printf '      note  %s\n' "$1"; }

fail_step() {
  local step_n="$1"
  local msg="$2"
  local resume_cmd
  resume_cmd=$(_resume_cmd "$step_n")
  log_err "$msg"
  cat <<EOF >&2

${_RED}${_BOLD}Bring-up halted at step ${step_n}.${_RESET}

  Resume after fixing the issue:
    ${resume_cmd}

  Operator-hand hint: take a Proxmox snapshot of the Pilot-VM BEFORE
  this step ('qm snapshot <vmid> pre-step-${step_n}') so that a
  rollback is available if the resume itself fails.

EOF
  exit 2
}

prompt_yes_no() {
  local question="$1"
  local default="${2:-y}"
  if [[ "$WAKIR_SKIP_PROMPTS" == "1" ]]; then
    case "$default" in
      [Yy]*) return 0 ;;
      *)     return 1 ;;
    esac
  fi
  local hint="[Y/n]"
  [[ "$default" == "n" ]] && hint="[y/N]"
  local answer=""
  read -r -p "      ${question} ${hint} " answer || answer=""
  answer=${answer:-$default}
  case "$answer" in
    [Yy]*) return 0 ;;
    *)     return 1 ;;
  esac
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

usage() {
  cat <<EOF
Usage: ${PROG} [--resume-from N] [--help]

One-shot bring-up for the Wakir Phase-1b single-org pilot VM. See
PROXMOX_BRING_UP_RECIPE.md for the manual / step-by-step variant.

Steps:
  1  Pre-Flight (CoreOS detection, Podman, Network)
  2  Toolbox container 'wakir-bringup'
  3  CLI tools (cosign, skopeo, jq, git) inside toolbox
  4  Repo clone -> \${WAKIR_REPO_ROOT}
  5  Image-pin resolve (cosign verify + skopeo digest cross-check)
  6  Quadlet units install + start (Networks, Volumes, SPIRE, NATS)
  7  NATS-KV bucket init for pilot org
  8  Smoke test (proxmox-bringup-smoke --org \${WAKIR_ORG_ID})

Env vars (see top of script for full list):
  WAKIR_ORG_ID              (default: acme)
  WAKIR_TRUST_DOMAIN        (default: wakir.test; auto-syncs with WAKIR_SIDE)
  WAKIR_SIDE                (default: wakir; alt: orbit, partner)
  WAKIR_PILOT_MODE          (default: single-org; alt: federation)
  WAKIR_PEER_SIDE           (federation-mode only; e.g. orbit)
  WAKIR_PEER_HOST           (federation-mode only; peer VM IP)
  WAKIR_SKIP_COSIGN_VERIFY  (default: 0; set 1 for tag-only quick-pilot)
  WAKIR_SKIP_PROMPTS        (default: 0; set 1 for headless / CI)
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --resume-from)
      RESUME_FROM="${2:-}"
      if ! [[ "$RESUME_FROM" =~ ^[1-8]$ ]]; then
        echo "[$PROG] ERROR: --resume-from expects 1..${TOTAL_STEPS}" >&2
        exit 1
      fi
      shift 2
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

# ---------------------------------------------------------------------------
# Pre-banner
# ---------------------------------------------------------------------------

cat <<EOF
${_BOLD}Wakir-Pilot-VM Bring-up${_RESET}
  Org-ID:        ${WAKIR_ORG_ID}
  Trust-Domain:  ${WAKIR_TRUST_DOMAIN}
  Side:          ${WAKIR_SIDE}
  Pilot-Mode:    ${WAKIR_PILOT_MODE}
  Peer-Side:     ${WAKIR_PEER_SIDE:-(not set; Operator-Hand for /etc/hosts)}
  Peer-Host:     ${WAKIR_PEER_HOST:-(not set; Operator-Hand for /etc/hosts)}
  Repo-Branch:   ${WAKIR_REPO_BRANCH}
  Repo-Root:     ${WAKIR_REPO_ROOT}
  Repo-Ref-Mode: ${WAKIR_REPO_REF_MODE}${WAKIR_REPO_REF:+ (ref: ${WAKIR_REPO_REF})}
  Resume-From:   ${RESUME_FROM}/${TOTAL_STEPS}
EOF

if [[ "$WAKIR_REPO_REF_MODE" != "track-remote" ]]; then
  cat <<EOF

${_YELLOW}${_BOLD}WARNING: WAKIR_REPO_REF_MODE=${WAKIR_REPO_REF_MODE}${_RESET}
  Step 4 will NOT move the checkout to the canonical
  origin/${WAKIR_REPO_BRANCH} tip. Whatever this run then measures, it
  measures against a tree that is not the branch. That is a legitimate
  thing to want -- it is how a change gets measured on the substrate
  before it is merged -- but it is not acceptance evidence, and the
  acceptance lanes will say so rather than print a PASS.
EOF
fi

if [[ "$WAKIR_SKIP_COSIGN_VERIFY" == "1" ]]; then
  cat <<EOF

${_YELLOW}${_BOLD}WARNING: WAKIR_SKIP_COSIGN_VERIFY=1${_RESET}
  Image-pin resolve will be skipped. Container pulls will run
  against tag-only references (no sha256 digest pin). This is
  DEV / QUICK-PILOT ONLY. For production-use, unset this flag and
  let step 5 resolve the digests via cosign + skopeo.
EOF
fi

echo

# ---------------------------------------------------------------------------
# Step 1: Pre-Flight
# ---------------------------------------------------------------------------

step_1_preflight() {
  log_step 1 "$TOTAL_STEPS" "Pre-Flight (CoreOS-Detection, Podman, Network)"

  # 1a. Root?
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    log_err "must run as root (use 'sudo')"
    return 2
  fi
  log_ok "running as root"

  # 1b. OS detection. We accept Fedora-CoreOS and warn for others.
  local os_id="" os_variant=""
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    os_id=$(. /etc/os-release && echo "${ID:-unknown}")
    os_variant=$(. /etc/os-release && echo "${VARIANT_ID:-}")
  fi
  case "$os_id" in
    fedora)
      if [[ "$os_variant" == "coreos" ]]; then
        log_ok "OS: Fedora CoreOS"
        # 1b-i. Live-vs-installed: CoreOS Live ISO sets
        # /run/coreos-installer or /etc/initrd-release.
        if [[ -e /run/coreos-installer ]] || [[ -e /etc/initrd-release ]]; then
          log_err "CoreOS detected in LIVE mode (not installed to disk)"
          cat <<'EOF' >&2

      Resolution: install CoreOS to disk before bring-up:

        sudo coreos-installer install /dev/sda \\
          --ignition-file your-ignition.ign

      Then reboot, log in, and re-run this script.
EOF
          exit 3
        fi
        log_ok "CoreOS booted from disk (not Live)"
      else
        log_ok "OS: Fedora (variant=${os_variant:-server})"
      fi
      ;;
    debian|ubuntu)
      log_warn "OS: ${os_id} (not Fedora-CoreOS; supported but path differs)"
      ;;
    *)
      log_warn "OS: ${os_id:-unknown} (unsupported; proceed at your own risk)"
      ;;
  esac

  # 1c. Podman present?
  if ! command -v "$WAKIR_BOOTSTRAP_PODMAN" >/dev/null 2>&1; then
    log_err "podman not on PATH"
    return 2
  fi
  local podman_version=""
  podman_version=$("$WAKIR_BOOTSTRAP_PODMAN" --version 2>/dev/null || echo "unknown")
  log_ok "podman: ${podman_version}"

  # 1d. systemd Quadlet support? Generator path is /usr/lib/systemd/
  # system-generators/podman-system-generator on recent versions.
  if [[ ! -e /usr/lib/systemd/system-generators/podman-system-generator ]] \
     && [[ ! -e /usr/libexec/podman/quadlet ]]; then
    log_warn "podman Quadlet generator not detected; daemon-reload may fail"
  else
    log_ok "podman Quadlet generator present"
  fi

  # 1e. Network: can we reach GitHub?
  if [[ "$WAKIR_SKIP_PROMPTS" != "1" ]]; then
    if "$WAKIR_BOOTSTRAP_CURL" -sSf -o /dev/null --max-time 10 \
         https://github.com 2>/dev/null; then
      log_ok "network: github.com reachable"
    else
      log_warn "network: github.com not reachable (offline-mode; step 4 may fail)"
    fi
  fi

  # 1f. Quadlet system path writable?
  if [[ ! -d /etc/containers/systemd ]]; then
    install -d -m 755 /etc/containers/systemd || return 2
    log_ok "/etc/containers/systemd created"
  else
    log_ok "/etc/containers/systemd present"
  fi

  # 1g. substance-fix (Bug-16, live bring-up bug report
  # 2026-05-14): explicit CLI-dependency check. Live-Bring-up-3 from-
  # scratch on Fedora-CoreOS revealed that the Step-5 image-pin
  # resolver relied on ``perl`` which is NOT on the FCOS host PATH.
  # The resolver silent-fell-through, the placeholder ``DIGEST_
  # PENDING_TOMAS_REVIEW`` remained in the bucket-init Quadlet, and
  # Step 7 crashed with ``invalid reference format``. The
  # resolver refactor (Bash-native) removes the perl dependency; this
  # pre-flight check codifies the full resolver / bootstrap CLI-set
  # so a future regression cannot silent-fall-through the same way.
  #
  # The list mirrors what the resolver + this bootstrap actually run.
  # Tools that ARE legitimately missing in step-1 context but get
  # installed later (cosign, skopeo) are intentionally NOT in this
  # list — step 3 brings them in via the toolbox.
  local _missing_cli=()
  local _required_cli=(
    "sed"        # resolver tag-tolerant fallback + step 6 inline edits
    "grep"       # used in step 6/7 unit-state checks
    "awk"        # legacy callers + journal parsers
    "cmp"        # _install_substituted idempotency comparator
    "sha256sum"  # step-6 applied-state fingerprint (convergence)
    "install"    # step 6/7 unit installs
    "mktemp"     # resolver atomic rewrite
    "stat"       # resolver mode-preserve
    "mv"         # resolver atomic rewrite
    "chmod"      # env-file 0600
    "tee"        # roster + env-file writes
    "head"       # token-parse pipeline
    "tr"         # token-parse pipeline
    "find"       # quadlet directory walk in step 6
    "jq"         # bringup-smoke + step 5 cosign/skopeo digest parse
  )
  local _t
  for _t in "${_required_cli[@]}"; do
    if ! command -v "$_t" >/dev/null 2>&1; then
      _missing_cli+=("$_t")
    fi
  done
  if [[ "${#_missing_cli[@]}" -gt 0 ]]; then
    log_err "missing required CLI tool(s) on host PATH: ${_missing_cli[*]}"
    log_note "install them BEFORE bring-up, e.g. on FCOS via"
    log_note "  sudo rpm-ostree install ${_missing_cli[*]}"
    log_note "  sudo systemctl reboot"
    log_note "or via toolbox if rpm-ostree-immutable rootfs is undesired."
    return 2
  fi
  log_ok "CLI tool inventory verified (${#_required_cli[@]} tools)"

  # 1h. Bash major version >= 5 — resolver tag-tolerant codepath uses
  # ``[[ =~ ]]`` + ``${BASH_REMATCH[@]}`` (Bash 5.x is FCOS-standard).
  # Older Bash 3 (macOS-default) would silently miss capture groups.
  if [[ "${BASH_VERSINFO[0]:-0}" -lt 5 ]]; then
    log_err "Bash major version >= 5 required; got ${BASH_VERSION:-unknown}"
    return 2
  fi
  log_ok "bash: ${BASH_VERSION}"

  return 0
}

# ---------------------------------------------------------------------------
# Step 2: Toolbox container for CLI tools
# ---------------------------------------------------------------------------
#
# CoreOS is rpm-ostree-immutable: /usr is read-only. CLI tools that
# would otherwise be 'dnf install'-ed (cosign, skopeo, jq) go into a
# toolbox container that has its own writable /usr.
#
# For non-CoreOS hosts we skip this step and use the host package
# manager directly in step 3.

step_2_toolbox() {
  log_step 2 "$TOTAL_STEPS" "Toolbox-Container 'wakir-bringup'"

  local os_variant=""
  if [[ -r /etc/os-release ]]; then
    os_variant=$(. /etc/os-release && echo "${VARIANT_ID:-}")
  fi
  if [[ "$os_variant" != "coreos" ]]; then
    log_note "non-CoreOS host: skip toolbox; use host package manager in step 3"
    return 0
  fi

  if ! command -v "$WAKIR_BOOTSTRAP_TOOLBOX" >/dev/null 2>&1; then
    log_warn "toolbox CLI not on PATH; falling back to plain podman container"
    # Soft path: create a long-lived container with fedora:latest.
    if "$WAKIR_BOOTSTRAP_PODMAN" inspect wakir-bringup >/dev/null 2>&1; then
      log_ok "container 'wakir-bringup' already present (re-use)"
      return 0
    fi
    "$WAKIR_BOOTSTRAP_PODMAN" create \
      --name wakir-bringup \
      --network host \
      -v /opt:/opt \
      -v /etc/containers/systemd:/etc/containers/systemd \
      docker.io/library/fedora:latest \
      sleep infinity >/dev/null \
      || { log_err "podman create wakir-bringup failed"; return 2; }
    "$WAKIR_BOOTSTRAP_PODMAN" start wakir-bringup >/dev/null \
      || { log_err "podman start wakir-bringup failed"; return 2; }
    log_ok "container 'wakir-bringup' created and started"
    return 0
  fi

  # toolbox path: idempotent create.
  if "$WAKIR_BOOTSTRAP_TOOLBOX" list -c 2>/dev/null \
       | grep -q '\bwakir-bringup\b'; then
    log_ok "toolbox 'wakir-bringup' already present"
    return 0
  fi
  "$WAKIR_BOOTSTRAP_TOOLBOX" create -y -c wakir-bringup >/dev/null \
    || { log_err "toolbox create wakir-bringup failed"; return 2; }
  log_ok "toolbox 'wakir-bringup' created"
  return 0
}

# ---------------------------------------------------------------------------
# Step 3: CLI tools
# ---------------------------------------------------------------------------

step_3_cli_tools() {
  log_step 3 "$TOTAL_STEPS" "CLI-Tools installieren (cosign, skopeo, jq, git)"

  local os_variant=""
  if [[ -r /etc/os-release ]]; then
    os_variant=$(. /etc/os-release && echo "${VARIANT_ID:-}")
  fi

  if [[ "$os_variant" == "coreos" ]]; then
    # CoreOS path: cosign is a static Go binary fetched from
    # GitHub Releases, dropped into /var/lib/wakir/bin (writable).
    # skopeo + jq + git are present in CoreOS via rpm-ostree.
    install -d -m 755 /var/lib/wakir/bin || return 2

    local cosign_dst="/var/lib/wakir/bin/cosign"
    if [[ -x "$cosign_dst" ]]; then
      log_ok "cosign already present at $cosign_dst"
    else
      local cosign_url="https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/cosign-linux-amd64"
      log_note "fetch cosign ${COSIGN_VERSION} from ${cosign_url}"
      if ! "$WAKIR_BOOTSTRAP_CURL" -sSfL -o "${cosign_dst}.tmp" \
              --max-time 60 "$cosign_url"; then
        log_err "cosign download failed"
        return 2
      fi
      chmod 0755 "${cosign_dst}.tmp"
      mv "${cosign_dst}.tmp" "$cosign_dst"
      log_ok "cosign installed at $cosign_dst"
    fi

    # Symlink into a directory on the default PATH so subsequent
    # invocations don't need an absolute path.
    if [[ ! -e /usr/local/bin/cosign ]]; then
      # /usr/local/bin is writable on CoreOS (not on /usr).
      ln -sf "$cosign_dst" /usr/local/bin/cosign \
        || log_warn "could not symlink cosign into /usr/local/bin"
    fi

    # skopeo + jq + git: present by default on CoreOS. Verify.
    local tool
    for tool in skopeo jq git; do
      if command -v "$tool" >/dev/null 2>&1; then
        log_ok "${tool} present"
      else
        log_warn "${tool} missing on CoreOS host; layering via rpm-ostree may be needed"
      fi
    done
  else
    # Non-CoreOS path: use the host package manager. We refuse to
    # surprise the operator with an unattended dnf install -- print
    # the apt/dnf command and ask for confirmation.
    log_note "non-CoreOS: install via host package manager"
    if command -v dnf >/dev/null 2>&1; then
      log_note "suggested: sudo dnf install -y cosign skopeo jq git"
    elif command -v apt-get >/dev/null 2>&1; then
      log_note "suggested: sudo apt-get install -y skopeo jq git  (cosign via GitHub release)"
    else
      log_warn "no recognized package manager"
    fi
    if ! prompt_yes_no "Proceed with the suggested install command above?" "y"; then
      log_warn "skip CLI-tool install (operator-hand follow-up)"
      return 0
    fi
    if command -v dnf >/dev/null 2>&1; then
      dnf install -y cosign skopeo jq git >/dev/null 2>&1 \
        || { log_err "dnf install failed"; return 2; }
    elif command -v apt-get >/dev/null 2>&1; then
      apt-get install -y skopeo jq git >/dev/null 2>&1 \
        || { log_err "apt-get install failed"; return 2; }
    fi
    log_ok "CLI tools installed"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Step 4: Repo clone
# ---------------------------------------------------------------------------

# Run one git command inside ${WAKIR_REPO_ROOT} and keep BOTH its output
# and its exit status.
#
# The form this replaces was a subshell of three chained git calls, each
# with its own ``>/dev/null 2>&1``, whose combined status is the status
# of the LAST command only:
#
#     ( cd "$root"
#       git fetch  ... >/dev/null 2>&1
#       git checkout ... >/dev/null 2>&1
#       git reset --hard "origin/$branch" >/dev/null 2>&1
#     ) || { log_err "git fetch/reset failed"; return 2; }
#
# A failing ``fetch`` -- no network, expired credentials, a remote that
# has moved -- was invisible there. ``reset --hard origin/<branch>``
# then succeeded against whatever the remote-tracking ref happened to
# hold from some earlier run, and the step logged
# ``repo updated to origin/<branch>``. The step reported success for an
# update that had not happened, and every later step ran against a tree
# nobody had checked.
#
# So: one call per invocation, status checked, output kept and surfaced
# on the failure path instead of discarded.
_git_repo() {
  local label="$1"
  shift
  local out="" rc=0
  out=$( cd "$WAKIR_REPO_ROOT" && "$WAKIR_BOOTSTRAP_GIT" "$@" 2>&1 ) || rc=$?
  if [[ $rc -ne 0 ]]; then
    log_err "git ${label} failed (rc=${rc}): git $*"
    if [[ -n "$out" ]]; then
      printf '%s\n' "$out" | tail -n 5 >&2
    fi
    return "$rc"
  fi
  printf '%s' "$out"
  return 0
}

# Same as _git_repo, but for measurement rather than for a load-bearing
# step: quiet on failure, because a question that cannot be answered is
# an answer here ("unknown"), not an error.
_git_repo_q() {
  ( cd "$WAKIR_REPO_ROOT" && "$WAKIR_BOOTSTRAP_GIT" "$@" ) 2>/dev/null
}

# Measure the tree step 4 ended up with, and write it down.
#
# The verdict is measured, not declared. It does not ask which mode the
# operator selected; it asks whether the commit checked out is the
# freshly fetched origin/<branch> tip and whether the worktree is clean.
# A pin that happens to land on the branch tip is therefore canonical,
# and a track-remote run whose fetch produced nothing comparable is not.
# The alternative -- trusting the mode flag -- would be one more check
# that reports what it was told instead of what is there.
# $1: "yes" when THIS run has already refreshed
#     refs/remotes/origin/<branch> through a checked fetch. The
#     track-remote arm has; the other two have not, and the refresh is
#     then this function's job.
_record_repo_provenance() {
  local already_fresh="${1:-no}"
  local head remote_tip remote_fresh worktree canonical reason requested
  local prov_file prov_dir

  # ``rev-parse <ref>`` echoes the ref back and exits non-zero when it
  # cannot resolve it, so taking its stdout without its status yields the
  # literal string "origin/main" as if it were a commit -- the same class
  # of defect this step is being repaired for. ``--verify --quiet``
  # prints nothing and fails cleanly instead.
  head=$(_git_repo_q rev-parse --verify --quiet HEAD) || head=""
  [[ -z "$head" ]] && head="unknown"

  # How old is the thing we are about to compare against?
  #
  # The verdict compares HEAD with refs/remotes/origin/<branch>, which is
  # A FILE ON THIS NODE, left there by some earlier run. Reading it
  # without knowing whether this run refreshed it would be exactly the
  # defect this step was repaired for, one level up. Defect A was "reset
  # to a stale tracking ref and call it an update"; this would be
  # "compare against a stale tracking ref and call it canonical".
  #
  # It is not hypothetical and it does not need a broken network. Pin a
  # tag that points at yesterday's commit -- the commit this node's
  # tracking ref still names -- and the comparison finds them equal.
  #
  #   track-remote  already refreshed, by a fetch whose status is checked
  #                 and whose failure aborts the step. Nothing to do.
  #   pin           fetches ONLY the requested ref. If that ref is a
  #                 branch name git refreshes the tracking ref
  #                 incidentally; if it is a tag or a pull ref, nothing
  #                 does. So: refresh it here, on purpose.
  #   keep          fetches nothing at all.
  #
  # The refspec is explicit rather than relying on git's opportunistic
  # remote-tracking update: a measurement should not depend on a side
  # effect.
  if [[ "$already_fresh" == "yes" ]]; then
    remote_fresh="yes"
  elif _git_repo_q fetch --depth 1 origin \
         "+refs/heads/${WAKIR_REPO_BRANCH}:refs/remotes/origin/${WAKIR_REPO_BRANCH}" \
         >/dev/null; then
    remote_fresh="yes"
  else
    remote_fresh="no"
    log_warn "could not refresh origin/${WAKIR_REPO_BRANCH} in this run; the tree cannot be compared against anything current"
  fi

  remote_tip=$(_git_repo_q rev-parse --verify --quiet \
    "refs/remotes/origin/${WAKIR_REPO_BRANCH}") || remote_tip=""
  [[ -z "$remote_tip" ]] && remote_tip="unknown"

  if [[ -n "$(_git_repo_q status --porcelain)" ]]; then
    worktree="dirty"
  else
    worktree="clean"
  fi

  if [[ "$WAKIR_REPO_REF_MODE" == "pin" ]]; then
    requested="$WAKIR_REPO_REF"
  else
    requested="$WAKIR_REPO_BRANCH"
  fi

  # Three outcomes, not two. "no" means the tree was measured and is not
  # the branch tip. "unmeasured" means the comparison did not happen --
  # a different statement, and the one the reader must not collapse into
  # either of the others. Same distinction as UNKNOWN on the reader side:
  # the absence of a measurement is not a failed measurement, and it is
  # certainly not a passed one.
  canonical="no"
  if [[ "$head" == "unknown" ]]; then
    canonical="unmeasured"
    reason="HEAD of ${WAKIR_REPO_ROOT} could not be read"
  elif [[ "$remote_fresh" != "yes" ]]; then
    canonical="unmeasured"
    reason="origin/${WAKIR_REPO_BRANCH} could not be refreshed in this run, so HEAD was compared against nothing current"
  elif [[ "$remote_tip" == "unknown" ]]; then
    canonical="unmeasured"
    reason="origin/${WAKIR_REPO_BRANCH} is not known on this node even after the refresh"
  elif [[ "$head" != "$remote_tip" ]]; then
    reason="HEAD ${head} is not the origin/${WAKIR_REPO_BRANCH} tip ${remote_tip}"
  elif [[ "$worktree" != "clean" ]]; then
    reason="HEAD is the origin/${WAKIR_REPO_BRANCH} tip but the worktree carries uncommitted modifications"
  else
    canonical="yes"
    reason="HEAD is the origin/${WAKIR_REPO_BRANCH} tip, freshly fetched in this run, and the worktree is clean"
  fi

  case "$canonical" in
    yes)
      log_ok "tree: ${head} (canonical ${WAKIR_REPO_BRANCH} tip, clean worktree)"
      ;;
    no)
      log_warn "tree: ${head} is NOT the canonical tree -- ${reason}"
      log_warn "a run against this tree is not acceptance evidence"
      ;;
    *)
      log_warn "tree: ${head} was NOT MEASURED -- ${reason}"
      log_warn "a run whose tree was not measured is not acceptance evidence"
      ;;
  esac

  # The record is load-bearing: a lane that cannot read one treats the
  # tree as unknown and refuses to report evidence. So failing to write
  # it fails the step, rather than leaving a run that looks fine and
  # cannot be attributed to a tree.
  prov_file="$WAKIR_REPO_PROVENANCE_FILE"
  prov_dir=$(dirname "$prov_file")
  if ! install -d -m 755 "$prov_dir" 2>/dev/null; then
    log_err "cannot create the provenance directory ${prov_dir}"
    return 2
  fi
  if ! cat >"$prov_file" <<EOF
# Written by wakir-pilot-bootstrap.sh step 4. Machine-read by the
# acceptance lanes via scripts/lib/repo-provenance.sh. Do not hand-edit:
# the point of the file is that it was produced by a measurement.
#
# Field order is load-bearing. The operator-controlled values
# (REQUESTED_REF, BRANCH, REPO_ROOT) stand BEFORE the verdict fields, so
# that a newline smuggled into one of them can only inject a line the
# real verdict line then overrides. Do not reorder.
WAKIR_PROVENANCE_SCHEMA=wakir-runtime/repo-provenance@2
WAKIR_PROVENANCE_RUN_ID=${WAKIR_PROVENANCE_RUN_ID}
WAKIR_PROVENANCE_WRITTEN_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)
WAKIR_PROVENANCE_REPO_ROOT=${WAKIR_REPO_ROOT}
WAKIR_PROVENANCE_BRANCH=${WAKIR_REPO_BRANCH}
WAKIR_PROVENANCE_REF_MODE=${WAKIR_REPO_REF_MODE}
WAKIR_PROVENANCE_REQUESTED_REF=${requested}
WAKIR_PROVENANCE_HEAD=${head}
WAKIR_PROVENANCE_REMOTE_TIP=${remote_tip}
WAKIR_PROVENANCE_REMOTE_TIP_FRESH=${remote_fresh}
WAKIR_PROVENANCE_WORKTREE=${worktree}
WAKIR_PROVENANCE_CANONICAL=${canonical}
WAKIR_PROVENANCE_REASON=${reason}
EOF
  then
    log_err "cannot write the provenance record ${prov_file}"
    return 2
  fi
  log_note "provenance record: ${prov_file}"
  return 0
}

step_4_repo_clone() {
  log_step 4 "$TOTAL_STEPS" \
    "Repo klonen nach ${WAKIR_REPO_ROOT} (ref-mode ${WAKIR_REPO_REF_MODE})"

  # (a) There has to be a checkout at all.
  if [[ ! -d "${WAKIR_REPO_ROOT}/.git" ]]; then
    if [[ "$WAKIR_REPO_REF_MODE" == "keep" ]]; then
      log_err "WAKIR_REPO_REF_MODE=keep, but there is no checkout at ${WAKIR_REPO_ROOT} to keep"
      return 2
    fi
    install -d -m 755 "$(dirname "$WAKIR_REPO_ROOT")" || return 2
    if ! "$WAKIR_BOOTSTRAP_GIT" clone \
           --depth 1 \
           --branch "$WAKIR_REPO_BRANCH" \
           "$WAKIR_REPO_URL" \
           "$WAKIR_REPO_ROOT" >/dev/null 2>&1; then
      log_err "git clone failed: ${WAKIR_REPO_URL} (branch ${WAKIR_REPO_BRANCH})"
      return 2
    fi
    log_ok "repo cloned"
  fi

  # (b) Say what is about to be destroyed, before destroying it.
  #
  # track-remote's ``reset --hard`` and pin's ``checkout --force`` both
  # discard tracked modifications; untracked files survive both. The pin
  # arm therefore introduces no new loss class -- the default arm has
  # behaved this way since the lane exists. Refusing to run on a dirty
  # checkout would be worse: the lane is unattended
  # (WAKIR_SKIP_PROMPTS=1) and it is the only path to live evidence, so
  # a refusal turns "the run discarded something nobody needed" into
  # "the run did not happen". But it should not happen silently: the
  # bring-up log is kept by the lane and quoted on every failure path.
  local pending=""
  if [[ "$WAKIR_REPO_REF_MODE" != "keep" ]]; then
    pending=$(_git_repo_q status --porcelain)
    if [[ -n "$pending" ]]; then
      log_warn "the checkout carries local changes; ${WAKIR_REPO_REF_MODE} discards the tracked ones (untracked files survive):"
      printf '%s\n' "$pending" | sed 's/^/      /'
      _git_repo_q diff --stat | sed 's/^/      /'
    fi
  fi

  # (c) Move it -- or deliberately do not -- to the requested ref.
  #
  # remote_ref_fresh records whether THIS arm left
  # refs/remotes/origin/<branch> refreshed. Only track-remote does; the
  # provenance measurement arranges its own refresh otherwise.
  local remote_ref_fresh="no"
  case "$WAKIR_REPO_REF_MODE" in
    track-remote)
      log_ok "repo present; fetching latest on ${WAKIR_REPO_BRANCH}"
      # Each of the three calls is load-bearing and each is checked. A
      # failed fetch stops here: continuing would reset the checkout to
      # a remote-tracking ref of unknown age, which is worse than not
      # updating at all, because it looks like an update.
      _git_repo "fetch" fetch --depth 1 origin "$WAKIR_REPO_BRANCH" \
        >/dev/null || { log_err "cannot reach origin; refusing to reset the checkout to a stale remote-tracking ref"; return 2; }
      _git_repo "checkout" checkout "$WAKIR_REPO_BRANCH" >/dev/null || return 2
      _git_repo "reset" reset --hard "origin/${WAKIR_REPO_BRANCH}" \
        >/dev/null || return 2
      log_ok "repo updated to origin/${WAKIR_REPO_BRANCH}"
      # The fetch above is checked and its failure returns 2, so
      # reaching this line means the tracking ref is current.
      remote_ref_fresh="yes"
      ;;
    pin)
      log_warn "WAKIR_REPO_REF_MODE=pin: moving the checkout to '${WAKIR_REPO_REF}', NOT to the ${WAKIR_REPO_BRANCH} tip"
      _git_repo "fetch-ref" fetch --depth 1 origin "$WAKIR_REPO_REF" \
        >/dev/null || return 2
      _git_repo "checkout-ref" checkout --force --detach FETCH_HEAD \
        >/dev/null || return 2
      log_ok "repo pinned to requested ref '${WAKIR_REPO_REF}'"
      ;;
    keep)
      log_warn "WAKIR_REPO_REF_MODE=keep: leaving the checkout at ${WAKIR_REPO_ROOT} exactly as it is; origin/${WAKIR_REPO_BRANCH} is NOT pulled"
      ;;
  esac

  # (d) Say which tree this run is about to use.
  _record_repo_provenance "$remote_ref_fresh" || return 2
  return 0
}

# ---------------------------------------------------------------------------
# Step 5: Image-pin resolve
# ---------------------------------------------------------------------------

step_5_image_pins() {
  log_step 5 "$TOTAL_STEPS" "Image-Pin-Resolve via cosign + skopeo (4 Images)"

  # Bug 4 substance-fix: when ``WAKIR_SKIP_COSIGN_VERIFY=1``
  # is set, the previous form returned immediately without resolving the
  # ``wakir-provisioner`` digest. The bucket-init Quadlet then started
  # with the literal ``DIGEST_PENDING_TOMAS_REVIEW`` placeholder in its
  # ``Image=`` line and Podman refused the pull. The fix: in skip-cosign
  # mode, fall through to a skopeo-only resolution path.
  #
  # Bug-36 substance-fix (Live-VM-Acceptance 2026-05-15
  # ~20:10 CEST): the prior skip-cosign branch resolved ONLY the
  # wakir-provisioner image and left ``DIGEST_PENDING_TOMAS_REVIEW`` in
  # spire-server-federation, spire-agent-federation, and the python-base
  # Containerfile pin. The four SPIRE/python Quadlets / Containerfiles
  # DO carry an ``@sha256:DIGEST_PENDING_TOMAS_REVIEW`` placeholder
  # despite the prior code comment claiming they ran "tag reference
  # only" (Bug-36 root-cause: the comment was wrong; the placeholders
  # were always there, the resolver was simply never asked to fill
  # them in the skip-cosign branch). The federation-mode Live-VM run
  # crashed at SPIRE-server start with ``parsing reference ...
  # invalid reference format``.
  #
  # Fix: in skip-cosign mode, run skopeo-only resolution for ALL four
  # images and call the resolver with the full digest argv (no
  # --provisioner-only). Skopeo is consistent across all four images
  # (DockerHub + ghcr.io both expose ``Digest`` in the inspect output)
  # and the resolver path is byte-identical to the cosign+skopeo
  # cross-check branch below.
  #
  # The ``--provisioner-only`` resolver flag stays in the resolver for
  # ad-hoc Operator-Hand re-runs that only need to rotate the
  # provisioner pin (e.g. after an image republish without a SPIRE
  # version bump).
  local resolver="${WAKIR_REPO_ROOT}/infra/spire/federation/proxmox/resolve-image-pins.sh"
  if [[ ! -x "$resolver" ]]; then
    log_err "resolver not found: ${resolver}"
    return 2
  fi

  # Bug-36-Härtung: announce the resolver trust-mode
  # explicitly so the bring-up log records which trust-base was used.
  # See docs/RESOLVER-TRUST-MODES.md for the threat-model.
  log_note "resolver trust-mode: ${WAKIR_RESOLVER_TRUST_MODE}"

  if [[ "$WAKIR_SKIP_COSIGN_VERIFY" == "1" ]]; then
    log_warn "WAKIR_SKIP_COSIGN_VERIFY=1 (skopeo-only-all-4); skopeo-only resolve for all 4 images (no Sigstore signature verification)"
    local image
    local -A skip_digests=()
    local skopeo_image
    # Bug-36: resolve all four pins via skopeo. The
    # ordering mirrors the cosign+skopeo branch below so log-output
    # is consistent between modes.
    for image in \
        ghcr.io/spiffe/spire-server:1.14.6 \
        ghcr.io/spiffe/spire-agent:1.14.6 \
        docker.io/library/python:3.13-slim \
        ghcr.io/wakir-labs/wakir-provisioner:0.1.4
    do
      log_note "skopeo-only resolve: ${image}"
      local d=""
      d=$(skopeo inspect "docker://${image}" 2>/dev/null \
        | jq -r '.Digest // empty' || echo "")
      if [[ -z "$d" ]]; then
        if [[ "$image" == ghcr.io/wakir-labs/wakir-provisioner:* ]]; then
          # Provisioner remains optional on first bring-up — the image
          # may not yet be published. Log + continue.
          log_note "wakir-provisioner skopeo inspect failed (image may not be published yet); skipping its pin substitution"
          continue
        fi
        log_err "skopeo inspect failed for ${image} in skip-cosign-mode"
        return 2
      fi
      skip_digests["$image"]="$d"
      log_ok "${image} -> ${d}"
    done

    local skip_args=(
      --spire-server-digest "${skip_digests["ghcr.io/spiffe/spire-server:1.14.6"]}"
      --spire-agent-digest  "${skip_digests["ghcr.io/spiffe/spire-agent:1.14.6"]}"
      --python-digest       "${skip_digests["docker.io/library/python:3.13-slim"]}"
      --root                "$WAKIR_REPO_ROOT"
      --apply
    )
    if [[ -n "${skip_digests["ghcr.io/wakir-labs/wakir-provisioner:0.1.4"]:-}" ]]; then
      skip_args+=(
        --wakir-provisioner-digest "${skip_digests["ghcr.io/wakir-labs/wakir-provisioner:0.1.4"]}"
      )
    fi

    if [[ "${WAKIR_SYNTHETIC_DIGESTS:-0}" == "1" ]]; then
      skip_args+=(--synthetic-digests)
    fi
    "$resolver" "${skip_args[@]}" \
      || { log_err "resolve-image-pins.sh --apply (skopeo-only) failed"; return 2; }
    log_ok "image-pin resolve applied (skopeo-only, skip-cosign-verify)"
    return 0
  fi

  # Bug-36-Härtung: mixed-mode (Sigstore-Outage-Fallback).
  # Cosign-verify on signed images; skopeo-fallback for the
  # SPIRE-allowlist only when the cosign step itself produced an empty
  # digest (proxy for Sigstore-outage). python:3.13-slim is already
  # skopeo-only in the cosign-strict branch below by upstream policy;
  # mixed-mode therefore overlaps with strict for that image.
  #
  # The allowlist is hardcoded — Operator-Hand cannot widen it without a
  # source-patch + Zone-C cross-review. See
  # docs/RESOLVER-TRUST-MODES.md for the threat-model.
  if [[ "$WAKIR_RESOLVER_TRUST_MODE" == "mixed" ]]; then
    log_warn "trust-mode=mixed (Sigstore-outage fallback); will use skopeo for SPIRE-allowlist if cosign fails"
    # The mixed-mode path is structurally identical to cosign-strict
    # except that cosign-failures on the SPIRE-allowlist are demoted
    # from rc=2-fatal to a logged skopeo-fallback. The control-flow
    # below (lines starting at "Pre-check: are placeholders still
    # present?") executes for mixed-mode too; the difference lives in
    # the cosign-verify error handling inside the per-image loop. The
    # variable below gates that demotion.
    : "${_KAI_MIXED_MODE_ALLOWLIST:=ghcr.io/spiffe/spire-server:1.14.6 ghcr.io/spiffe/spire-agent:1.14.6}"
  fi

  # Pre-check: are placeholders still present? If not, the repo state
  # has already been pinned (e.g. baked-in pin) -- nothing to do.
  if ! grep -q DIGEST_PENDING_TOMAS_REVIEW \
         "${WAKIR_REPO_ROOT}/quadlet/" \
         "${WAKIR_REPO_ROOT}/infra/spire/" -r 2>/dev/null; then
    log_ok "no DIGEST_PENDING_TOMAS_REVIEW placeholders found; already pinned"
    return 0
  fi

  local image
  local -A digests=()
  #: wakir-provisioner is OPTIONAL on first bring-up
  # because the image may not yet be published. The loop tries it
  # last; a skopeo-failure for wakir-provisioner is non-fatal and
  # falls back to the placeholder-retain path (the Quadlet will not
  # start the bucket-init service until Operator-Hand re-resolves).
  # Bug 4 substance-fix: bump the wakir-provisioner tag
  # from 0.1.0 to 0.1.2 (the BSL-1.1 relicensed image; AR-Decision
  # 2026-05-13). 0.1.0 carried four wheels (nats-py + cryptography +
  # rfc8785 + jsonschema); 0.1.2 carries nats-py only post-PR #33
  # Wirelang-Import-Disentanglement. The bucket-init Quadlet (Image=
  # ghcr.io/wakir-labs/wakir-provisioner:0.1.4@sha256:DIGEST_...) is
  # the single consumer of this digest.
  for image in \
      ghcr.io/spiffe/spire-server:1.14.6 \
      ghcr.io/spiffe/spire-agent:1.14.6 \
      docker.io/library/python:3.13-slim \
      ghcr.io/wakir-labs/wakir-provisioner:0.1.4
  do
    log_note "cosign + skopeo cross-check: ${image}"

    local cosign_digest=""
    local skopeo_digest=""

    # cosign verify path:
    #   * ghcr.io/spiffe/*: Sigstore-keyless against the SPIRE
    #     upstream OIDC identity (IMAGE_PINS.md §2.1).
    #   * ghcr.io/wakir-labs/wakir-provisioner: Sigstore-keyless
    #     against the wakir-labs build-workflow OIDC identity
    #     (IMAGE_PINS.md §2.5).
    #   * docker.io/library/python:3.13-slim: DockerHub, no
    #     Sigstore signing — skopeo-only (IMAGE_PINS.md §2.4).
    if [[ "$image" == ghcr.io/spiffe/* ]]; then
      cosign_digest=$(cosign verify \
        --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
        --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
        "$image" 2>/dev/null \
        | jq -r '.[0].critical.image."docker-manifest-digest" // empty' \
        || echo "")
      if [[ -z "$cosign_digest" ]]; then
        # Bug-36-Härtung: mixed-mode demotes cosign-failure
        # on the SPIRE-allowlist from rc=2-fatal to logged skopeo-
        # fallback. See docs/RESOLVER-TRUST-MODES.md mixed-mode section.
        if [[ "$WAKIR_RESOLVER_TRUST_MODE" == "mixed" ]] \
           && [[ " $_KAI_MIXED_MODE_ALLOWLIST " == *" $image "* ]]; then
          log_warn "trust-mode=mixed: cosign verify failed for ${image}; falling back to skopeo (allowlist hit)"
        else
          log_err "cosign verify failed or produced empty digest for ${image}"
          return 2
        fi
      fi
    elif [[ "$image" == ghcr.io/wakir-labs/wakir-provisioner:* ]]; then
      cosign_digest=$(cosign verify \
        --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
        --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
        "$image" 2>/dev/null \
        | jq -r '.[0].critical.image."docker-manifest-digest" // empty' \
        || echo "")
      if [[ -z "$cosign_digest" ]]; then
        #: image may not yet be published on first
        # bring-up. Log + continue with empty digest; the skopeo
        # step below decides whether to treat this as fatal.
        log_note "wakir-provisioner cosign verify failed (image may not be published yet)"
      fi
    fi

    # skopeo inspect (cross-check OR primary for DockerHub).
    skopeo_digest=$(skopeo inspect "docker://${image}" 2>/dev/null \
      | jq -r '.Digest // empty' || echo "")
    if [[ -z "$skopeo_digest" ]]; then
      if [[ "$image" == ghcr.io/wakir-labs/wakir-provisioner:* ]]; then
        # Non-fatal for the optional image: skip its substitution
        # and continue with the rest of the loop.
        log_note "skopeo inspect failed for ${image} (image may not be published yet); skipping its pin substitution"
        continue
      fi
      log_err "skopeo inspect failed or produced empty digest for ${image}"
      return 2
    fi

    if [[ -n "$cosign_digest" ]] && [[ "$cosign_digest" != "$skopeo_digest" ]]; then
      log_err "digest mismatch for ${image}:"
      log_err "  cosign: ${cosign_digest}"
      log_err "  skopeo: ${skopeo_digest}"
      log_err "halt rollout; Zone-C cross-review (tomás) required"
      return 2
    fi

    digests["$image"]="$skopeo_digest"
    log_ok "${image} -> ${skopeo_digest}"
  done

  # Build the resolver argv. wakir-provisioner is only passed if the
  # loop above resolved a digest for it.
  local resolver_args=(
    --spire-server-digest "${digests["ghcr.io/spiffe/spire-server:1.14.6"]}"
    --spire-agent-digest  "${digests["ghcr.io/spiffe/spire-agent:1.14.6"]}"
    --python-digest       "${digests["docker.io/library/python:3.13-slim"]}"
    --root                "$WAKIR_REPO_ROOT"
    --apply
  )
  if [[ -n "${digests["ghcr.io/wakir-labs/wakir-provisioner:0.1.4"]:-}" ]]; then
    resolver_args+=(
      --wakir-provisioner-digest "${digests["ghcr.io/wakir-labs/wakir-provisioner:0.1.4"]}"
    )
  else
    log_note "skipping wakir-provisioner pin (image not yet resolvable; bucket-init service will not start until Operator-Hand re-runs the resolver)"
  fi

  if [[ "${WAKIR_SYNTHETIC_DIGESTS:-0}" == "1" ]]; then
    resolver_args+=(--synthetic-digests)
  fi
  "$resolver" "${resolver_args[@]}" \
    || { log_err "resolve-image-pins.sh --apply failed"; return 2; }

  log_ok "image-pin resolve applied"
  return 0
}

# ---------------------------------------------------------------------------
# Helper: chown a Podman named-volume backing directory to uid:gid
# 1000:1000 and verify the result via ``stat``. Idempotent and
# defensive — safe to invoke before every ``systemctl start`` of a
# Quadlet container that mounts the volume (Bug-22 substance
# fix, see step 6g rationale block).
#
# Args:
#   $1  volume name (e.g. ``wakir-spire-agent-wakir-data``)
#   $2  invocation context tag (logged on failure, e.g.
#       ``step-6g-initial`` or ``step-6h-pre-server-start``)
#
# Returns:
#   0  ownership confirmed at ``1000:1000``
#   2  hard failure — caller MUST propagate
#
# Side effects:
#   * Surfaces chown stderr (Bug-21 invariant).
#   * Stat-verifies post-chown owner (Bug-21 invariant).
#   * With WAKIR_BOOTSTRAP_DEBUG=1: emits a before-and-after stat
#     line on stderr for the next operator's diagnosis.
# ---------------------------------------------------------------------------

_chown_volume_with_verify() {
  local v="$1"
  local ctx="$2"
  local vol_dir actual_owner pre_owner

  vol_dir=$("$WAKIR_BOOTSTRAP_PODMAN" volume inspect "$v" \
    --format '{{.Mountpoint}}' 2>/dev/null || echo "")
  if [[ -z "$vol_dir" ]] || [[ ! -d "$vol_dir" ]]; then
    log_err "podman volume inspect ${v} returned empty/missing path (ctx=${ctx})"
    return 2
  fi

  if [[ "${WAKIR_BOOTSTRAP_DEBUG:-0}" == "1" ]]; then
    pre_owner=$(stat -c '%u:%g' "$vol_dir" 2>/dev/null || echo "stat-err")
    log_note "debug ${ctx}: pre-chown ${vol_dir} owner=${pre_owner}"
  fi

  if ! chown -R 1000:1000 "$vol_dir"; then
    log_err "chown 1000:1000 ${vol_dir} failed (volume ${v}, ctx=${ctx})"
    return 2
  fi

  # Verify ownership actually took effect on the directory itself.
  # ``-R`` walks the tree, but the directory's own owner is the
  # post-chown invariant the SPIRE process cares about.
  actual_owner=$(stat -c '%u:%g' "$vol_dir")
  if [[ "$actual_owner" != "1000:1000" ]]; then
    log_err "chown verification failed: ${vol_dir} owner=${actual_owner} (expected 1000:1000, volume ${v}, ctx=${ctx})"
    return 2
  fi

  if [[ "${WAKIR_BOOTSTRAP_DEBUG:-0}" == "1" ]]; then
    log_note "debug ${ctx}: post-chown ${vol_dir} owner=${actual_owner} (ok)"
  fi
  return 0
}

# ---------------------------------------------------------------------------
# Helper: defensive re-chown sweep for the volume set mounted by a
# specific Quadlet container, invoked immediately before ``systemctl
# start`` to close the Bug-22 race window. The volume set per
# container is hard-coded here (mirrors the ``Volume=`` lines in the
# corresponding Quadlet templates) so future template drift surfaces
# as a missing pre-start chown rather than a silent regression.
#
# Args:
#   $1  container kind: ``server`` | ``agent`` | ``nats``
#   $2  side (e.g. ``wakir``); ignored for ``nats``
#
# Returns:
#   0  all volumes confirmed at ``1000:1000``
#   2  hard failure — caller MUST propagate
# ---------------------------------------------------------------------------

_pre_start_chown_sweep() {
  local kind="$1"
  local side="$2"
  local ctx="pre-${kind}-start"
  local v vols=()

  case "$kind" in
    server)
      # Mirror of wakir-spire-server-federation.container Volume= lines.
      vols=(
        "wakir-spire-server-federation-${side}-data"
        "wakir-spire-server-federation-${side}-sockets"
        "wakir-spire-server-federation-${side}-bundles"
        "wakir-spire-server-federation-${side}-upstream-ca"
      )
      ;;
    agent)
      # Mirror of wakir-spire-agent-federation.container Volume= lines.
      # Note: the agent mounts the server-side bundles volume ro,Z; we
      # still re-chown it here defensively.
      vols=(
        "wakir-spire-agent-${side}-data"
        "wakir-spire-agent-${side}-sockets"
        "wakir-spire-server-federation-${side}-bundles"
      )
      ;;
    nats)
      # Mirror of wakir-nats.container Volume= line. The NATS Quadlet
      # pins User=1000/Group=1000 -- note that compose/nats.yaml does
      # NOT (it leaves the image's root default and a root-owned
      # volume). The two tracks differ here, and this chown belongs to
      # the Quadlet track: uid 1000 must own the JetStream store or
      # NATS aborts with "storage directory is not writable". The
      # bucket-init service is a one-shot client and does not mount its
      # own volume.
      vols=(
        "wakir-nats-jetstream-data"
      )
      ;;
    *)
      log_err "_pre_start_chown_sweep: unknown kind ${kind}"
      return 2
      ;;
  esac

  for v in "${vols[@]}"; do
    # Volume may not yet exist for NATS on a first bring-up; create
    # idempotently. Server/agent volumes are pre-created in step 6g.
    "$WAKIR_BOOTSTRAP_PODMAN" volume create --ignore "$v" >/dev/null 2>&1 || true
    _chown_volume_with_verify "$v" "$ctx" || return 2
  done
  return 0
}

# ---------------------------------------------------------------------------
# Helper: wait for a systemd unit to actually become ``is-active`` after
# a ``systemctl start`` returns. The start call is fire-and-forget — it
# returns as soon as systemd has accepted the job, while the unit is
# still ``activating``. The Quadlet-generated containers spend
# noticeable wall-time in ``activating`` on first-boot (image-pull-from-
# cache, container-init, server-attestation handshake, SVID-caching,
# Workload-API socket bind). The bring-up-1/2/3/4/5/6 smoke
# runs all observed this race: the bootstrap returned success and the
# smoke-test (attempts=6, ~30s) caught the unit still in
# ``activating`` state.
#
# Bug-25 substance fix: after each ``systemctl
# start`` of a long-running Quadlet container, block until ``is-active
# --quiet`` returns 0, capped at ``WAKIR_BOOTSTRAP_WAIT_ACTIVE_TIMEOUT``
# seconds. The 300s default covers a cold-cache image pull on a slow
# Proxmox-VE node; bring-up-6 first-run reached ``active`` in 15-25s
# wall-clock. ``WAKIR_BOOTSTRAP_WAIT_ACTIVE_POLL`` controls the poll
# interval (5s default — fast enough to keep the OK line close to
# actual ``active`` transition, slow enough not to spam systemd).
#
# Args:
#   $1  unit name (e.g. ``wakir-spire-server-federation-wakir.service``)
#
# Returns:
#   0  unit reached ``active`` within the timeout
#   2  hard failure (timeout exhausted; caller MUST propagate)
#
# Side effects:
#   * On timeout: dumps ``systemctl status <unit> --no-pager`` to stderr
#     so the next operator sees the failure surface immediately.
#   * Logs the wall-clock seconds the wait took on success (operator
#     calibration for future timeout tuning).
# ---------------------------------------------------------------------------

_wait_for_service_active() {
  local unit="$1"
  local timeout="${WAKIR_BOOTSTRAP_WAIT_ACTIVE_TIMEOUT:-300}"
  local poll="${WAKIR_BOOTSTRAP_WAIT_ACTIVE_POLL:-5}"
  local elapsed=0

  # Fast path: many idempotent re-runs hit a unit that was already
  # active when systemctl start was invoked. Probe once before sleeping.
  if "$WAKIR_BOOTSTRAP_SYSTEMCTL" is-active --quiet "$unit"; then
    log_ok "${unit} is-active (already, t=0s)"
    return 0
  fi

  while [[ $elapsed -lt $timeout ]]; do
    "${WAKIR_BOOTSTRAP_SLEEP:-sleep}" "$poll" 2>/dev/null \
      || sleep "$poll"
    elapsed=$((elapsed + poll))
    if "$WAKIR_BOOTSTRAP_SYSTEMCTL" is-active --quiet "$unit"; then
      log_ok "${unit} is-active (after ${elapsed}s wait)"
      return 0
    fi
  done

  log_err "${unit} did not reach is-active within ${timeout}s (Bug-25 race window not closed)"
  log_note "diagnose: journalctl -u ${unit} -n 100 --no-pager"
  "$WAKIR_BOOTSTRAP_SYSTEMCTL" status "$unit" --no-pager >&2 2>/dev/null || true
  return 2
}

# ---------------------------------------------------------------------------
# Helper: wait for the SPIRE-Agent Workload-API socket to be bound
# inside the agent container. ``systemd is-active`` returning ``active``
# means the container init succeeded; it does NOT guarantee that the
# SPIRE-Agent has finished server-attestation and bound
# ``/run/spire/agent-sockets/api.sock``. Bring-up-3/4/5/6 Run-2 evidence:
# units active, healthcheck still fails because the workload-API
# socket has not been created yet.
#
# Bug-25 substance fix: after the agent unit reaches
# ``is-active``, additionally block until ``podman exec ... test -S
# /run/spire/agent-sockets/api.sock`` returns 0. This closes the
# second race window inside step_6_quadlet, before bootstrap completes
# and the smoke-test fires.
#
# Args:
#   $1  agent container name (e.g. ``wakir-spire-agent-wakir``)
#
# Returns:
#   0  socket exists inside the agent container
#   2  hard failure (timeout; caller MUST propagate)
# ---------------------------------------------------------------------------

_wait_for_workload_api_socket() {
  # Bug-27 fix: SPIRE-Agent ist distroless-Container
  # (ghcr.io/spiffe/spire-agent: nur ``spire-agent``-binary, kein ``test``/
  # ``sh``/Coreutils). The variant via ``podman exec <ctr> test
  # -S <path>`` returnt IMMER rc=127 ("executable file 'test' not found
  # in PATH") — Loop läuft 120s leer und meldet "not bound" obwohl Socket
  # längst da ist (Live-Diagnose 2026-05-15 ~01:51 UTC bestätigt).
  #
  # Korrektur: Socket über HOST-Pfad des named-volume prüfen. Konvention:
  #   container ``wakir-spire-agent-<SIDE>`` → vol ``wakir-spire-agent-<SIDE>-sockets``
  #
  # Hermetic-Bypass: ``WAKIR_BOOTSTRAP_SKIP_SOCKET_WAIT=1`` deaktiviert den
  # Wait. Der e2e-container-Test setzt das Flag weil sein podman-Stub kein
  # echtes Unix-Socket-File erzeugen kann (fedora-base-image hat weder
  # python3 noch socat default-installiert). Live-VM darf das Flag NICHT
  # setzen — der echte Bring-up MUSS auf das echte Socket warten.
  local container="$1"

  if [[ "${WAKIR_BOOTSTRAP_SKIP_SOCKET_WAIT:-0}" == "1" ]]; then
    log_ok "${container} workload-API socket wait skipped (WAKIR_BOOTSTRAP_SKIP_SOCKET_WAIT=1, hermetic-stub-mode)"
    return 0
  fi

  local timeout="${WAKIR_BOOTSTRAP_WAIT_SOCKET_TIMEOUT:-120}"
  local poll="${WAKIR_BOOTSTRAP_WAIT_SOCKET_POLL:-5}"
  local elapsed=0

  local sockets_vol="${container}-sockets"
  local sockets_dir
  sockets_dir=$("$WAKIR_BOOTSTRAP_PODMAN" volume inspect "$sockets_vol" \
    --format '{{.Mountpoint}}' 2>/dev/null || echo "")
  if [[ -z "$sockets_dir" ]] || [[ ! -d "$sockets_dir" ]]; then
    log_err "podman volume inspect ${sockets_vol} returned empty/missing path"
    return 2
  fi
  local host_socket="${sockets_dir}/api.sock"

  while [[ $elapsed -lt $timeout ]]; do
    if [[ -S "$host_socket" ]]; then
      log_ok "${container} workload-API socket bound (after ${elapsed}s wait, host-path ${host_socket})"
      return 0
    fi
    "${WAKIR_BOOTSTRAP_SLEEP:-sleep}" "$poll" 2>/dev/null \
      || sleep "$poll"
    elapsed=$((elapsed + poll))
  done

  log_err "${container} workload-API socket ${host_socket} not bound within ${timeout}s (Bug-25/27 race window)"
  log_note "diagnose: ls -la ${sockets_dir}/ ; journalctl -u wakir-spire-agent-*.service -n 100 --no-pager"
  return 2
}

# ---------------------------------------------------------------------------
#: peer-host /etc/hosts wiring helper
#
# When WAKIR_PILOT_MODE=federation AND both WAKIR_PEER_SIDE +
# WAKIR_PEER_HOST are set, append (if missing) an /etc/hosts entry
# mapping ``spire-server-<peer_side>`` to the peer VM's IP. This is
# the substance-fix for the M-3 Live-Trial: the PR #59 Phase-2c
# live-counterpart-adapter pins URLs at ``https://spire-server-<peer-
# side>:8443`` — that hostname MUST resolve to the peer VM. Without
# the /etc/hosts entry, the federation-bundle-sync-reachable smoke
# check FAILs with DNS-NXDOMAIN and `Connection refused` cascades
# back through the adapter test in the test_live_int_live_partner_vm.
#
# Idempotent: a marker comment (``# wakir-bootstrap: peer-side
# <peer_side>``) on the entry's line lets the bootstrap recognise the
# entry across re-runs and update only if the IP changed.
#
# Sandbox-Boundary: the test surface (test_pilot_bootstrap_peer_host.py)
# injects WAKIR_BOOTSTRAP_HOSTS=/tmp/.../fake-hosts so the bootstrap
# never touches /etc/hosts during hermetic tests.
# ---------------------------------------------------------------------------

_install_peer_host_entry() {
  if [[ "$WAKIR_PILOT_MODE" != "federation" ]]; then
    return 0
  fi
  if [[ -z "$WAKIR_PEER_SIDE" || -z "$WAKIR_PEER_HOST" ]]; then
    log_note "peer-host wiring skipped (WAKIR_PEER_SIDE or WAKIR_PEER_HOST unset)"
    log_note "  Operator-Hand alternative: add ``${WAKIR_PEER_HOST:-<peer-ip>} spire-server-${WAKIR_PEER_SIDE:-<peer-side>}`` to ${WAKIR_BOOTSTRAP_HOSTS}"
    return 0
  fi
  local peer_dns="spire-server-${WAKIR_PEER_SIDE}"
  local marker="# wakir-bootstrap: peer-side ${WAKIR_PEER_SIDE}"
  local entry="${WAKIR_PEER_HOST}	${peer_dns}	${marker}"
  if [[ ! -f "$WAKIR_BOOTSTRAP_HOSTS" ]]; then
    log_err "hosts file not found: ${WAKIR_BOOTSTRAP_HOSTS}"
    return 2
  fi
  if grep -qE "[[:space:]]${peer_dns}[[:space:]]" "$WAKIR_BOOTSTRAP_HOSTS" 2>/dev/null; then
    # Entry already exists. Re-write the line if marker present AND
    # the IP differs (operator-hand override of peer host).
    local existing_line
    existing_line=$(grep -E "[[:space:]]${peer_dns}[[:space:]]" "$WAKIR_BOOTSTRAP_HOSTS" | head -1)
    if echo "$existing_line" | grep -qF "$marker"; then
      local existing_ip
      existing_ip=$(echo "$existing_line" | awk '{print $1}')
      if [[ "$existing_ip" == "$WAKIR_PEER_HOST" ]]; then
        log_ok "peer-host /etc/hosts entry already present for ${peer_dns} -> ${WAKIR_PEER_HOST}"
        return 0
      fi
      # Update the IP in place.
      local tmp
      tmp=$(mktemp)
      grep -vE "[[:space:]]${peer_dns}[[:space:]]" "$WAKIR_BOOTSTRAP_HOSTS" > "$tmp" || true
      printf '%s\n' "$entry" >> "$tmp"
      install -m 644 "$tmp" "$WAKIR_BOOTSTRAP_HOSTS" \
        || { log_err "peer-host /etc/hosts update failed"; rm -f "$tmp"; return 2; }
      rm -f "$tmp"
      log_ok "peer-host /etc/hosts entry updated: ${peer_dns} -> ${WAKIR_PEER_HOST} (was ${existing_ip})"
      return 0
    fi
    log_warn "peer-host /etc/hosts entry for ${peer_dns} exists without wakir-bootstrap marker; not touching (Operator-Hand-owned)"
    return 0
  fi
  printf '\n%s\n' "$entry" >> "$WAKIR_BOOTSTRAP_HOSTS" \
    || { log_err "peer-host /etc/hosts append failed"; return 2; }
  log_ok "peer-host /etc/hosts entry added: ${peer_dns} -> ${WAKIR_PEER_HOST}"
}

# ---------------------------------------------------------------------------
# Step-6 convergence substrate: "installed" is not "applied"
#
# Measured evidence (Operator-Hand, Live-VM, 2026-09-21/22): step 6
# rendered a Quadlet unit, wrote it to /etc/containers/systemd, ran
# ``systemctl daemon-reload``, found the service ``active`` and then
# SKIPPED the start -- logging ``OK <unit> already active``. The unit
# file on disk carried ``PublishPort=0.0.0.0:8443:8443`` while the
# running container still bound ``127.0.0.1:8443``, because that
# container had been created two runs earlier. ``ss -ltn`` and the
# unit file disagreed; the log said OK. A ``systemctl restart`` made
# the installed directive live immediately.
#
# Generalised: every Quadlet change -- image pin, mount, env,
# resource limit, PublishPort -- could be installed, logged OK and
# never applied. The bootstrap was idempotent, not convergent.
#
# The substrate below closes that gap with two independent
# change-signals per service unit:
#
#   1. In-run signal. Every step-6 install path goes through
#      ``_install_if_changed``. Where ``cmp -s`` fails and ``install``
#      runs, the owning service unit is marked via
#      ``_note_config_change`` -> ``_mark_unit_changed``. Precise and
#      state-free, but blind to a change made by an EARLIER run.
#   2. Applied-state fingerprint. After a successful start/restart
#      ``_record_unit_applied`` writes the SHA-256 of every file that
#      defines the unit (Quadlet ``.container``, the bind-mounted
#      config file, the referenced ``.volume`` / ``.network`` units)
#      to ``<applied-state-dir>/<unit>.applied``. The next run
#      compares the current fingerprint against that record. This is
#      the signal that catches the 2026-09-21 case, where the unit
#      came from run N-1 and the container from run N-2.
#
# Why a content fingerprint and not the unit-file mtime: mtime says
# nothing about content (an operator ``touch``; a re-render that
# produced identical bytes), and a container that systemd restarted
# on its own AFTER the file changed but BEFORE the daemon-reload
# would look newer than a unit it never applied. The fingerprint
# compares what is installed against what was last known to run.
#
# Cost, stated plainly: on the FIRST run after this change no unit has
# a record, so every running unit counts as "convergence state
# unknown" and is restarted once. That one-time convergence pass is
# deliberate -- on a substrate where an unapplied unit may have been
# sitting there for months, "assume it is fine" is the assumption that
# produced this bug. From the second run on, a run without a change
# restarts nothing.
#
# Env overrides (hermetic tests; production uses the defaults):
#   WAKIR_BOOTSTRAP_QUADLET_DIR       default /etc/containers/systemd
#   WAKIR_BOOTSTRAP_ETC_DIR           default /etc/wakir
#   WAKIR_BOOTSTRAP_APPLIED_STATE_DIR default /var/lib/wakir/bootstrap/applied
# ---------------------------------------------------------------------------

# Newline-delimited set of service units whose on-disk definition this
# run rewrote. Populated by _mark_unit_changed, read by
# _unit_definition_drifted.
WAKIR_CHANGED_UNITS=""

# Human-readable reason why the last _unit_definition_drifted call
# returned "needs applying". Surfaced in the OK line so the operator
# sees WHY a restart happened.
_WAKIR_CONVERGE_REASON=""

_applied_state_dir() {
  printf '%s' "${WAKIR_BOOTSTRAP_APPLIED_STATE_DIR:-/var/lib/wakir/bootstrap/applied}"
}

_quadlet_dir() {
  printf '%s' "${WAKIR_BOOTSTRAP_QUADLET_DIR:-/etc/containers/systemd}"
}

_wakir_etc_dir() {
  printf '%s' "${WAKIR_BOOTSTRAP_ETC_DIR:-/etc/wakir}"
}

# Mark a service unit as "its definition was rewritten in this run".
# Idempotent; logs once per unit.
_mark_unit_changed() {
  local unit="$1"
  case "${WAKIR_CHANGED_UNITS}" in
    *"|${unit}|"*) return 0 ;;
  esac
  WAKIR_CHANGED_UNITS="${WAKIR_CHANGED_UNITS}|${unit}|"
  log_note "definition changed in this run: ${unit} (will be applied, not just installed)"
  return 0
}

_unit_is_marked_changed() {
  local unit="$1"
  case "${WAKIR_CHANGED_UNITS}" in
    *"|${unit}|"*) return 0 ;;
  esac
  return 1
}

# Map a just-written config path to the service unit(s) it defines.
# Emits one unit name per line; empty output = file belongs to no
# service unit we start here (then nothing is marked).
_units_for_config_path() {
  local base
  base="$(basename "$1")"
  local side="${WAKIR_SIDE}"
  local server_unit="wakir-spire-server-federation-${side}.service"
  local agent_unit="wakir-spire-agent-${side}.service"
  local nats_unit="wakir-nats.service"
  case "$base" in
    "wakir-spire-server-federation-${side}.container" \
      |"spire-server-${side}.conf")
      printf '%s\n' "$server_unit"
      ;;
    "wakir-spire-agent-${side}.container" \
      |"spire-agent-${side}.conf")
      printf '%s\n' "$agent_unit"
      ;;
    "wakir-nats.container")
      printf '%s\n' "$nats_unit"
      ;;
    "wakir-spire-server-federation-${side}-"*.volume)
      # The agent mounts the server's bundles volume read-only.
      printf '%s\n' "$server_unit" "$agent_unit"
      ;;
    "wakir-spire-agent-${side}-"*.volume)
      printf '%s\n' "$agent_unit"
      ;;
    "wakir-nats-"*.volume)
      printf '%s\n' "$nats_unit"
      ;;
    *.network)
      # A changed network definition needs every container on that
      # network re-created, not just re-declared.
      printf '%s\n' "$server_unit" "$agent_unit" "$nats_unit"
      ;;
    *)
      : # not a definition of a unit this step starts
      ;;
  esac
}

# Record that <path> was (re)written in this run.
_note_config_change() {
  local path="$1"
  local unit
  while IFS= read -r unit; do
    [[ -n "$unit" ]] || continue
    _mark_unit_changed "$unit"
  done < <(_units_for_config_path "$path")
  return 0
}

# Content-idempotent install with a change-signal.
#
# Bug 5 kept the "do not overwrite an identical file" guard; Bug-40
# adds the other half: where the guard does NOT hold, the write is
# recorded so step 6h/6j can apply it instead of installing it and
# hoping.
_install_if_changed() {
  local src="$1"
  local target="$2"
  if [[ -f "$target" ]] && cmp -s "$src" "$target"; then
    return 0
  fi
  install -m 644 "$src" "$target" || return 1
  _note_config_change "$target"
  return 0
}

# Read the join-token that step 6i injected into an already-installed
# agent unit. Empty output when the file is absent or still carries the
# placeholder. See the call site in step 6d for why this exists.
_carried_join_token() {
  local unit_file="$1"
  if [[ ! -f "$unit_file" ]]; then
    return 0
  fi
  local tok
  tok=$(sed -n \
    's/^Exec=.*-joinToken[[:space:]]\{1,\}\([^[:space:]]\{1,\}\).*$/\1/p' \
    "$unit_file" | head -1)
  if [[ "$tok" == "WAKIR_JOIN_TOKEN_PLACEHOLDER" ]]; then
    return 0
  fi
  printf '%s' "$tok"
  return 0
}

# Every file that defines <unit>. Missing files are fine (they are
# fingerprinted as "absent", which is itself a state worth noticing).
_unit_tracked_files() {
  local unit="$1"
  local side="${WAKIR_SIDE}"
  local qdir edir
  qdir="$(_quadlet_dir)"
  edir="$(_wakir_etc_dir)"
  case "$unit" in
    "wakir-spire-server-federation-${side}.service")
      printf '%s\n' \
        "${qdir}/wakir-spire-server-federation-${side}.container" \
        "${edir}/spire-federation/spire-server-${side}.conf" \
        "${qdir}/wakir-spire-server-federation-${side}-data.volume" \
        "${qdir}/wakir-spire-server-federation-${side}-sockets.volume" \
        "${qdir}/wakir-spire-server-federation-${side}-bundles.volume" \
        "${qdir}/wakir-spire-server-federation-${side}-upstream-ca.volume" \
        "${qdir}/wakir-orchestrator.network" \
        "${qdir}/wakir-federation.network"
      ;;
    "wakir-spire-agent-${side}.service")
      printf '%s\n' \
        "${qdir}/wakir-spire-agent-${side}.container" \
        "${edir}/spire-agent-${side}.conf" \
        "${qdir}/wakir-spire-agent-${side}-data.volume" \
        "${qdir}/wakir-spire-agent-${side}-sockets.volume" \
        "${qdir}/wakir-spire-server-federation-${side}-bundles.volume" \
        "${qdir}/wakir-orchestrator.network" \
        "${qdir}/wakir-federation.network"
      ;;
    "wakir-nats.service")
      printf '%s\n' \
        "${qdir}/wakir-nats.container" \
        "${qdir}/wakir-nats-jetstream-data.volume" \
        "${qdir}/wakir-orchestrator.network"
      ;;
    *)
      : # unknown unit -> empty fingerprint, handled by the caller
      ;;
  esac
}

# SHA-256 fingerprint of a unit's definition set, one line per file,
# sorted by path so the output is stable across runs.
_unit_config_fingerprint() {
  local unit="$1"
  local f h
  while IFS= read -r f; do
    [[ -n "$f" ]] || continue
    if [[ -f "$f" ]]; then
      h="$(sha256sum < "$f")"
      h="${h%% *}"
    else
      h="absent"
    fi
    printf '%s  %s\n' "$h" "${f##*/}"
  done < <(_unit_tracked_files "$unit" | LC_ALL=C sort)
}

# Persist "this definition is what the running container was created
# from". Called ONLY after a successful start/restart, or when the
# running unit was verified in sync.
#
# A failure to persist is a warning, never a hard stop: the worst case
# is that the next run cannot tell installed from applied and restarts
# once more. Failing the bring-up over a bookkeeping file would be the
# wrong trade.
_record_unit_applied() {
  local unit="$1"
  local dir
  dir="$(_applied_state_dir)"
  if ! install -d -m 700 "$dir" 2>/dev/null; then
    log_warn "applied-state dir ${dir} not writable; next run cannot tell installed from applied"
    return 0
  fi
  local tmp
  tmp="$(mktemp)" || return 0
  if ! _unit_config_fingerprint "$unit" > "$tmp"; then
    rm -f "$tmp"
    log_warn "could not fingerprint ${unit}; applied-state not recorded"
    return 0
  fi
  if ! install -m 600 "$tmp" "${dir}/${unit}.applied"; then
    log_warn "applied-state record for ${unit} not written"
  fi
  rm -f "$tmp"
  return 0
}

# Does the installed definition of <unit> still need to be applied?
#
# Returns 0 (yes, restart) with _WAKIR_CONVERGE_REASON set, or 1 (no,
# the running container was created from exactly this definition).
_unit_definition_drifted() {
  local unit="$1"
  local stamp
  stamp="$(_applied_state_dir)/${unit}.applied"

  if _unit_is_marked_changed "$unit"; then
    _WAKIR_CONVERGE_REASON="definition rewritten in this run"
    return 0
  fi
  if [[ ! -f "$stamp" ]]; then
    _WAKIR_CONVERGE_REASON="no applied-state record: running configuration unverifiable"
    return 0
  fi
  if ! _unit_config_fingerprint "$unit" | cmp -s - "$stamp"; then
    _WAKIR_CONVERGE_REASON="installed definition differs from the last applied one (change from an earlier run)"
    return 0
  fi
  _WAKIR_CONVERGE_REASON="installed definition equals the applied one"
  return 1
}

# Converge one service unit: start it if it is not running, restart it
# if it runs from a definition other than the installed one, leave it
# alone if it is in sync.
#
# Args:
#   $1  unit name
#   $2  kind for _pre_start_chown_sweep (server|agent|nats|"")
#
# Returns:
#   0  unit is running from the installed definition
#   2  hard failure (caller MUST propagate)
#
# The Bug-25 wait points run on BOTH the start and the restart path --
# a restart re-opens exactly the same activating/socket-bind race as a
# cold start.
_converge_service_unit() {
  local unit="$1"
  local kind="$2"
  local side="${WAKIR_SIDE}"
  local action=""

  if ! "$WAKIR_BOOTSTRAP_SYSTEMCTL" is-active --quiet "$unit"; then
    action="start"
    _WAKIR_CONVERGE_REASON="unit not running"
  elif _unit_definition_drifted "$unit"; then
    action="restart"
  else
    log_ok "${unit} active, running configuration matches the installed unit (${_WAKIR_CONVERGE_REASON}; no restart)"
    _record_unit_applied "$unit"
    return 0
  fi

  if [[ "$kind" == "agent" ]]; then
    # Refuse to apply an agent unit that still carries the join-token
    # placeholder. Before convergence this was survivable by accident:
    # the unit was never applied, so nobody noticed that step 6i had
    # left it incoherent -- until a VM reboot started the agent with
    # ``-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER`` and it crash-looped
    # (Bug-37). Now that the bootstrap applies what it installs, that
    # unit must not be applied; it must be reported.
    local agent_unit_file
    agent_unit_file="$(_quadlet_dir)/wakir-spire-agent-${side}.container"
    if [[ -f "$agent_unit_file" ]] \
       && grep -q "WAKIR_JOIN_TOKEN_PLACEHOLDER" "$agent_unit_file"; then
      log_err "${unit}: installed unit still carries WAKIR_JOIN_TOKEN_PLACEHOLDER -- refusing to ${action} the agent into it"
      log_note "step 6i must inject a join-token before the agent unit is applied"
      log_note "diagnose: grep -n joinToken ${agent_unit_file}"
      return 2
    fi
  fi

  if [[ -n "$kind" ]]; then
    # Bug-22 defensive re-chown immediately before the
    # start: podman reconciles volume ownership at container create,
    # and a restart creates a new container.
    _pre_start_chown_sweep "$kind" "$side" || return 2
  fi
  "$WAKIR_BOOTSTRAP_SYSTEMCTL" reset-failed "$unit" 2>/dev/null || true
  if ! "$WAKIR_BOOTSTRAP_SYSTEMCTL" "$action" "$unit"; then
    log_err "systemctl ${action} ${unit} failed"
    log_note "diagnose: journalctl -u ${unit} -n 50 --no-pager"
    return 2
  fi
  log_ok "${unit} ${action} issued (${_WAKIR_CONVERGE_REASON})"
  _wait_for_service_active "$unit" || return 2
  if [[ "$kind" == "agent" ]]; then
    _wait_for_workload_api_socket "wakir-spire-agent-${side}" || return 2
  fi
  _record_unit_applied "$unit"
  return 0
}

# ---------------------------------------------------------------------------
# ADR-0076 step 2: the long-lived upstream CA root.
#
# Until now the SPIRE-Server was its own root. It minted a fresh
# self-signed root every ``ca_ttl`` (24h) and pruned the expired one,
# so every copy of the trust bundle had a shelf life of one day. That
# is the mechanism behind the 127 dead days: not that nobody staged an
# anchor, but that no anchor could have survived being staged.
#
# With ``UpstreamAuthority "disk"`` in the server config the server
# mints intermediates against a root that lives here. This helper
# creates that root ONCE per side and then never touches it again.
#
# The single most important property of this function is what it does
# NOT do: it does not regenerate. Replacing the root invalidates every
# SVID and every bundle copy on BOTH federation sides -- the ADR calls
# that out as a bilateral maintenance-window operation, not a re-run.
# A bootstrap that quietly rolled the root on a repeat invocation would
# be a one-command outage of the peer. So:
#
#   * both files present and the cert still valid  -> keep, log, return
#   * exactly one of the two present               -> HARD ABORT
#   * neither present                              -> generate
#
# The half-present case aborts rather than heals on purpose. A missing
# key next to a present cert means either an interrupted first run or
# somebody deleting things by hand; both want a human, and the
# "helpful" branch of that decision is the one that takes the peer
# down.
#
# Material shape (ADR-0076): EC P-256, self-signed, multi-year,
# key 0600, cert 0644, owned by uid 1000 (the container user), in its
# own named volume, never in the repository and never in git.
# ---------------------------------------------------------------------------

_upstream_ca_volume() {
  printf 'wakir-spire-server-federation-%s-upstream-ca' "${1}"
}

_ensure_upstream_ca_material() {
  local side="$1"
  local vol dir crt key days subject
  vol="$(_upstream_ca_volume "$side")"
  days="${WAKIR_UPSTREAM_CA_DAYS:-1826}"
  # Test hooks, same shape as WAKIR_BOOTSTRAP_SKIP_SOCKET_WAIT: the
  # hermetic suite has no root and cannot chown to uid 1000. Defaults
  # are the production values; nothing reads these on a real host.
  local ca_uid="${WAKIR_UPSTREAM_CA_UID:-1000}"
  local ca_gid="${WAKIR_UPSTREAM_CA_GID:-1000}"
  local do_chown="${WAKIR_UPSTREAM_CA_CHOWN:-1}"

  "$WAKIR_BOOTSTRAP_PODMAN" volume create --ignore "$vol" >/dev/null 2>&1 || true
  dir=$("$WAKIR_BOOTSTRAP_PODMAN" volume inspect --format '{{.Mountpoint}}' "$vol" 2>/dev/null) \
    || { log_err "podman volume inspect ${vol} failed"; return 2; }
  dir="${dir%$'\n'}"
  if [[ -z "$dir" || ! -d "$dir" ]]; then
    log_err "could not resolve a mountpoint for volume ${vol}"
    return 2
  fi

  crt="${dir}/root.crt"
  key="${dir}/root.key"

  if [[ -f "$crt" && -f "$key" ]]; then
    # Present. Verify it is still usable and leave it alone.
    if ! openssl x509 -in "$crt" -noout >/dev/null 2>&1; then
      log_err "upstream CA certificate at ${crt} does not parse"
      log_note "this is operator-hand territory: a broken root is a bilateral cutover, not a re-run (ADR-0076 migration)"
      return 2
    fi
    if ! openssl x509 -in "$crt" -noout -checkend 0 >/dev/null 2>&1; then
      log_err "upstream CA certificate at ${crt} has EXPIRED"
      log_note "renewal replaces the trust-domain root and must be done bilaterally in a maintenance window (ADR-0076)"
      return 2
    fi
    local not_after
    not_after=$(openssl x509 -in "$crt" -noout -enddate 2>/dev/null | sed 's/^notAfter=//')
    log_ok "upstream CA root retained (notAfter=${not_after:-unknown}) -- not regenerated"
    _verify_upstream_ca_material "$crt" "$key" || return 2
    return 0
  fi

  if [[ -f "$crt" || -f "$key" ]]; then
    log_err "upstream CA material is half-present in ${dir} (cert=$([[ -f "$crt" ]] && echo yes || echo no), key=$([[ -f "$key" ]] && echo yes || echo no))"
    log_note "refusing to generate over a partial root: a new root invalidates every SVID and bundle on BOTH federation sides"
    log_note "operator-hand: decide whether to restore the missing half or run a bilateral root cutover (ADR-0076 migration)"
    return 2
  fi

  # Neither present -> first generation.
  if ! command -v openssl >/dev/null 2>&1; then
    log_err "openssl not found on PATH -- cannot create the upstream CA root"
    return 2
  fi
  local ossl_major
  ossl_major=$(openssl version 2>/dev/null | sed -n 's/^OpenSSL \([0-9]\+\).*/\1/p')
  if [[ -z "$ossl_major" || "$ossl_major" -lt 3 ]]; then
    log_err "openssl 3.x required (found: $(openssl version 2>/dev/null || echo none))"
    log_note "the generation call below uses -noenc and -addext, both 3.x surface"
    return 2
  fi

  subject="/O=Wakir Labs/CN=${WAKIR_TRUST_DOMAIN} upstream CA"
  local tmp_crt="${dir}/.root.crt.tmp.$$"
  local tmp_key="${dir}/.root.key.tmp.$$"

  log_note "creating upstream CA root for ${WAKIR_TRUST_DOMAIN} (EC P-256, ${days} days) in volume ${vol}"
  if ! openssl req -x509 \
        -newkey ec -pkeyopt ec_paramgen_curve:P-256 \
        -noenc \
        -keyout "$tmp_key" -out "$tmp_crt" \
        -days "$days" \
        -subj "$subject" \
        -addext "basicConstraints=critical,CA:TRUE" \
        -addext "keyUsage=critical,keyCertSign,cRLSign" \
        >/dev/null 2>&1; then
    rm -f "$tmp_crt" "$tmp_key"
    log_err "openssl req -x509 failed while creating the upstream CA root"
    return 2
  fi

  chmod 0600 "$tmp_key" || { rm -f "$tmp_crt" "$tmp_key"; log_err "chmod 0600 on the CA key failed"; return 2; }
  chmod 0644 "$tmp_crt" || { rm -f "$tmp_crt" "$tmp_key"; log_err "chmod 0644 on the CA cert failed"; return 2; }
  if [[ "$do_chown" == "1" ]]; then
    chown "${ca_uid}:${ca_gid}" "$tmp_key" "$tmp_crt" \
      || { rm -f "$tmp_crt" "$tmp_key"; log_err "chown ${ca_uid}:${ca_gid} on the CA material failed"; return 2; }
  fi

  _verify_upstream_ca_material "$tmp_crt" "$tmp_key" \
    || { rm -f "$tmp_crt" "$tmp_key"; return 2; }

  # Rename the KEY last: a reader that sees the cert without the key
  # hits the half-present abort above rather than a server that starts
  # against a root it cannot sign with.
  mv -f "$tmp_crt" "$crt" || { rm -f "$tmp_crt" "$tmp_key"; log_err "rename of the CA cert failed"; return 2; }
  mv -f "$tmp_key" "$key" || { log_err "rename of the CA key failed"; return 2; }

  local mode_key mode_crt owner_key
  mode_key=$(stat -c '%a' "$key" 2>/dev/null || echo "")
  mode_crt=$(stat -c '%a' "$crt" 2>/dev/null || echo "")
  if [[ "$mode_key" != "600" || "$mode_crt" != "644" ]]; then
    log_err "upstream CA material landed with key=${mode_key:-?} cert=${mode_crt:-?}; expected 600 / 644"
    return 2
  fi
  if [[ "$do_chown" == "1" ]]; then
    owner_key=$(stat -c '%u:%g' "$key" 2>/dev/null || echo "")
    if [[ "$owner_key" != "${ca_uid}:${ca_gid}" ]]; then
      log_err "upstream CA key landed with owner=${owner_key:-?}; expected ${ca_uid}:${ca_gid}"
      return 2
    fi
  fi

  log_ok "upstream CA root created (${vol}: root.crt 0644, root.key 0600, uid ${ca_uid}) -- not in git, not backed up off-VM"
  log_note "replacing this root later is a BILATERAL maintenance-window operation; it invalidates every SVID and bundle on both sides"
  return 0
}

# Assert the material is what the SPIRE ``disk`` UpstreamAuthority
# plugin needs as a ROOT CA: exactly one self-signed certificate with
# CA:TRUE, and a key that belongs to it.
#
# The key/cert binding check is the one that matters. A cert next to
# somebody else's key produces a server that starts, logs nothing
# unusual, and fails at the first CSR -- hours later, in a log nobody
# reads.
_verify_upstream_ca_material() {
  local crt="$1" key="$2"

  local cert_count
  cert_count=$(grep -c -- '-----BEGIN CERTIFICATE-----' "$crt" 2>/dev/null || echo 0)
  if [[ "$cert_count" -ne 1 ]]; then
    log_err "upstream CA cert file holds ${cert_count} certificates; root-CA operation needs exactly one (ADR-0076 / plugin doc)"
    return 2
  fi

  if ! openssl x509 -in "$crt" -noout -text 2>/dev/null | grep -q 'CA:TRUE'; then
    log_err "upstream CA certificate is not a CA certificate (basicConstraints CA:TRUE missing)"
    return 2
  fi

  local subj issuer
  subj=$(openssl x509 -in "$crt" -noout -subject 2>/dev/null)
  issuer=$(openssl x509 -in "$crt" -noout -issuer 2>/dev/null)
  if [[ "${subj#subject=}" != "${issuer#issuer=}" ]]; then
    log_err "upstream CA certificate is not self-signed (subject != issuer); root-CA operation requires a self-signed root"
    return 2
  fi

  local cert_pub key_pub
  cert_pub=$(openssl x509 -in "$crt" -noout -pubkey 2>/dev/null)
  key_pub=$(openssl pkey -in "$key" -pubout 2>/dev/null)
  if [[ -z "$cert_pub" || -z "$key_pub" || "$cert_pub" != "$key_pub" ]]; then
    log_err "upstream CA key does not belong to the upstream CA certificate"
    return 2
  fi

  return 0
}

# ---------------------------------------------------------------------------
# ADR-0076 step 3: stage the agent's bootstrap trust anchor.
#
# Runs between server start (6h) and agent start (6j). Delegates to
# ``bin/wakir-spire-stage-bootstrap-anchor`` so the bring-up and the
# 30-minute re-staging timer execute the SAME code -- a staging path
# that drifts from its own refresh path is two mechanisms, and the
# second one is always the one nobody tested.
#
# A failure here aborts the bring-up. That is the point: the whole
# defect class this ADR addresses is a substrate that came up looking
# healthy with an empty anchor directory.
# ---------------------------------------------------------------------------

_stager_installed_path() { printf '/var/lib/wakir/bin/wakir-spire-stage-bootstrap-anchor'; }

_install_anchor_stager() {
  local src="${WAKIR_REPO_ROOT}/infra/spire/federation/bin/wakir-spire-stage-bootstrap-anchor"
  local dst
  dst="$(_stager_installed_path)"
  if [[ ! -f "$src" ]]; then
    log_err "anchor stager not found in repo: ${src}"
    return 2
  fi
  install -d -m 755 "$(dirname "$dst")" || return 2
  install -m 0755 "$src" "$dst" || { log_err "install of the anchor stager failed"; return 2; }
  log_ok "anchor stager installed at ${dst}"
  return 0
}

_stage_bootstrap_anchor() {
  local side="$1"
  local stager
  stager="$(_stager_installed_path)"
  [[ -x "$stager" ]] || { log_err "anchor stager missing or not executable: ${stager}"; return 2; }

  if ! WAKIR_STAGE_PODMAN="$WAKIR_BOOTSTRAP_PODMAN" "$stager" --side "$side"; then
    log_err "bootstrap trust anchor could not be staged for side ${side}"
    log_note "the agent's trust_bundle_path would be an empty directory -- the exact state this substrate spent 127 days in"
    log_note "diagnose: ${WAKIR_BOOTSTRAP_PODMAN} exec wakir-spire-server-federation-${side} /opt/spire/bin/spire-server bundle show -format spiffe"
    return 2
  fi
  log_ok "bootstrap trust anchor staged into the ${side} bundles volume"
  return 0
}

# ---------------------------------------------------------------------------
# ADR-0076 step 4: the re-staging timer.
#
# ``ca_ttl`` stays at 24h by decision, so the signing intermediate
# still rotates daily. A single staged anchor at bring-up time would
# reproduce the May half-life with extra steps. The timer re-runs the
# stager every 30 minutes -- well inside the rotation window and cheap
# (one podman exec, one rename).
#
# Plain systemd units, not Quadlet: /etc/containers/systemd is read by
# the podman system generator and only for container/volume/network
# unit types. Same split the recovery-drill timer already uses.
# ---------------------------------------------------------------------------

_install_restage_timer() {
  local side="$1"
  local src_dir="${WAKIR_REPO_ROOT}/infra/spire/federation/quadlet"
  local sysd="${WAKIR_BOOTSTRAP_SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
  local unit="wakir-spire-bootstrap-anchor-restage-${side}"
  local f

  install -d -m 755 "$sysd" || return 2
  for f in service timer; do
    local src="${src_dir}/wakir-spire-bootstrap-anchor-restage.${f}"
    if [[ ! -f "$src" ]]; then
      log_err "restage unit template not found: ${src}"
      return 2
    fi
    _install_substituted_plain "$src" "${sysd}/${unit}.${f}" \
        -e "s|<SIDE>|${side}|g" \
        -e "s|<STAGER_PATH>|$(_stager_installed_path)|g" \
      || { log_err "install of ${src} failed"; return 2; }
  done

  "$WAKIR_BOOTSTRAP_SYSTEMCTL" daemon-reload \
    || { log_err "daemon-reload after restage-unit install failed"; return 2; }
  if ! "$WAKIR_BOOTSTRAP_SYSTEMCTL" enable --now "${unit}.timer"; then
    log_err "could not enable ${unit}.timer"
    log_note "without it the staged anchor ages out under the 24h ca_ttl and the substrate dies the same death as in May"
    return 2
  fi
  log_ok "${unit}.timer enabled (re-stages the bootstrap anchor every 30 min)"
  return 0
}

# Same render-then-install-if-changed shape as step 6's
# ``_install_substituted``, but usable outside step_6_quadlet (that one
# is a nested function and only exists while the step runs).
_install_substituted_plain() {
  local src="$1" target="$2"
  shift 2
  local tmp
  tmp=$(mktemp) || return 1
  sed "$@" "$src" > "$tmp" || { rm -f "$tmp"; return 1; }
  _install_if_changed "$tmp" "$target" || { rm -f "$tmp"; return 1; }
  rm -f "$tmp"
  return 0
}

# ---------------------------------------------------------------------------
# Step 6: Quadlet units
# ---------------------------------------------------------------------------

step_6_quadlet() {
  log_step 6 "$TOTAL_STEPS" "Quadlet-Units installieren (Networks, Volumes, SPIRE, NATS)"

  #: peer-host /etc/hosts entry for Cross-VM federation.
  # No-op in single-org mode. See _install_peer_host_entry header.
  _install_peer_host_entry || return 2

  local quadlet_src="${WAKIR_REPO_ROOT}/quadlet"
  local fed_src="${WAKIR_REPO_ROOT}/infra/spire/federation/quadlet"
  local agent_src="${WAKIR_REPO_ROOT}/infra/spire/agent/quadlet"
  local dst="${WAKIR_BOOTSTRAP_QUADLET_DIR:-/etc/containers/systemd}"
  # Cross-VM-Federation substance: side is no longer
  # hardcoded; the WAKIR_SIDE env-var (validated in the post-defaults
  # block) drives Quadlet-naming, config-file selection, and the
  # SERVER_DNS NetworkAlias substitution.
  local side="${WAKIR_SIDE}"

  if [[ ! -d "$quadlet_src" ]]; then
    log_err "quadlet source not found: ${quadlet_src}"
    return 2
  fi

  # Helper: install $1 (source) to $2 (dest), substituting <SIDE>
  # and other tokens in the file CONTENT. Skipped (idempotent) when
  # dest already matches the source-after-substitution.
  # Bug 5: bootstrap Phase 6 must be safely re-runnable after operator
  # manual fixes -- if the rendered content matches what's already on
  # disk, do not overwrite.
  _install_substituted() {
    local src="$1"
    local target="$2"
    shift 2
    # Remaining args are alternating sed-expr pairs ("-e" "EXPR" ...).
    local tmp
    tmp=$(mktemp)
    sed "$@" "$src" > "$tmp" || { rm -f "$tmp"; return 1; }
    # Bug-40: the write-or-skip decision AND the
    # change-signal it emits live in _install_if_changed, so every
    # step-6 install path feeds the same convergence bookkeeping.
    _install_if_changed "$tmp" "$target" || { rm -f "$tmp"; return 1; }
    rm -f "$tmp"
    return 0
  }

  # 6a. Networks
  local f
  for f in \
      "${quadlet_src}/wakir-orchestrator.network" \
      "${fed_src}/wakir-federation.network"
  do
    if [[ -f "$f" ]]; then
      local target="$dst/$(basename "$f")"
      _install_if_changed "$f" "$target" \
        || { log_err "install $f failed"; return 2; }
    fi
  done
  log_ok "network units installed"

  # 6b. Volumes (with per-side substitution).
  #
  # Bug 2: source filenames in the federation/agent
  # quadlet directories are side-agnostic (e.g.
  # ``wakir-spire-server-federation-data.volume``), but the
  # SPIRE-Server-Federation container references the per-side form
  # ``wakir-spire-server-federation-<SIDE>-data.volume`` (and the
  # agent references ``wakir-spire-server-federation-<SIDE>-bundles.
  # volume``). The bootstrap must therefore install each federation
  # volume file with a per-side renamed destination basename PLUS
  # substitute ``<SIDE>`` in the file content.
  #
  # Naming convention (mirror of the per-side Container ContainerName
  # / unit name convention):
  #   server: wakir-spire-server-federation-${side}-{data,sockets,bundles}.volume
  #   agent:  wakir-spire-agent-${side}-{data,sockets}.volume
  # Top-level ``quadlet/*.volume`` files are side-agnostic and keep
  # their original basename (no rename, no content sub).
  local v
  # 6b-i. Top-level (side-agnostic) volumes.
  for v in "${quadlet_src}"/*.volume; do
    [[ -f "$v" ]] || continue
    local target="$dst/$(basename "$v")"
    _install_if_changed "$v" "$target" \
      || { log_err "install $v failed"; return 2; }
  done

  # 6b-ii. Federation server volumes: rename destination to embed
  # ``-${side}-`` between ``federation`` and the kind suffix.
  for v in "${fed_src}"/*.volume; do
    [[ -f "$v" ]] || continue
    local base dest_base
    base=$(basename "$v")
    # wakir-spire-server-federation-data.volume
    #   -> wakir-spire-server-federation-${side}-data.volume
    # wakir-spire-server-federation-sockets.volume
    #   -> wakir-spire-server-federation-${side}-sockets.volume
    # wakir-spire-server-federation-bundles.volume
    #   -> wakir-spire-server-federation-${side}-bundles.volume
    #   wakir-spire-server-federation-upstream-ca.volume
    #     -> wakir-spire-server-federation-${side}-upstream-ca.volume
    dest_base=$(printf '%s' "$base" \
      | sed "s/^wakir-spire-server-federation-\(data\|sockets\|bundles\|upstream-ca\)\.volume$/wakir-spire-server-federation-${side}-\1.volume/")
    if [[ "$dest_base" == "$base" ]] \
       && ! [[ "$base" =~ ^wakir-spire-server-federation-(data|sockets|bundles|upstream-ca)\.volume$ ]]; then
      # Unexpected federation volume name -- pass through with content sub only.
      :
    fi
    _install_substituted "$v" "$dst/$dest_base" \
        -e "s/<SIDE>/${side}/g" \
      || { log_err "install $v failed"; return 2; }
  done

  # 6b-iii. Agent volumes: rename destination to embed ``-${side}-``
  # between ``agent`` and the kind suffix. Source files are
  # ``wakir-spire-agent-federation-{data,sockets}.volume`` but the
  # agent container references ``wakir-spire-agent-<SIDE>-{data,
  # sockets}.volume`` -- so we drop the literal ``federation-``
  # token from the destination basename and insert ``${side}-``.
  for v in "${agent_src}"/*.volume; do
    [[ -f "$v" ]] || continue
    local base dest_base
    base=$(basename "$v")
    # wakir-spire-agent-federation-data.volume
    #   -> wakir-spire-agent-${side}-data.volume
    # wakir-spire-agent-federation-sockets.volume
    #   -> wakir-spire-agent-${side}-sockets.volume
    dest_base=$(printf '%s' "$base" \
      | sed "s/^wakir-spire-agent-federation-\(data\|sockets\)\.volume$/wakir-spire-agent-${side}-\1.volume/")
    _install_substituted "$v" "$dst/$dest_base" \
        -e "s/<SIDE>/${side}/g" \
      || { log_err "install $v failed"; return 2; }
  done
  log_ok "volume units installed"

  # 6c. SPIRE-Server-Federation container (per-side substitution).
  #
  # Bug 7 substance-fix: WAKIR_PILOT_MODE selects which
  # server-config variant the bootstrap installs.
  #   * single-org -> spire-server-pilot-single-org.conf
  #   * federation -> spire-server-${side}.conf
  # See top-of-file rationale block at WAKIR_PILOT_MODE definition.
  #
  # substance-fix (M-3 Live-Trial): wire <HOST_BUNDLE_BIND>
  # from WAKIR_PILOT_MODE. Single-org pilots keep the bundle-endpoint
  # loopback-only (no peer to expose it to). Federation pilots bind the
  # bundle-endpoint on 0.0.0.0 so a cross-VM peer can fetch the bundle
  # over the host LAN or the Proxmox-internal bridge. The gRPC API
  # (8081) stays loopback-only in both modes — see the Quadlet
  # template's <HOST_BUNDLE_BIND> header for the security rationale.
  local host_bundle_bind="127.0.0.1"
  if [[ "$WAKIR_PILOT_MODE" == "federation" ]]; then
    host_bundle_bind="0.0.0.0"
  fi
  local server_tpl="${fed_src}/wakir-spire-server-federation.container"
  if [[ -f "$server_tpl" ]]; then
    local server_sed_args=(
      -e "s/<SIDE>/${side}/g"
      -e "s/<HOST_BUNDLE_PORT>/8443/g"
      -e "s/<HOST_GRPC_PORT>/8082/g"
      -e "s|<HOST_BUNDLE_BIND>|${host_bundle_bind}|g"
    )
    if [[ "$WAKIR_PILOT_MODE" == "single-org" ]]; then
      # ADR-0076 scopes ``UpstreamAuthority "disk"`` to the three
      # federation server configs. The single-org config does not
      # declare it, so mounting the root material into a single-org
      # server would place a private key in front of a process that
      # has no use for it. Same sed-delete shape as the agent's
      # peer-bundle mount two blocks down.
      server_sed_args+=(
        -e "\|wakir-spire-server-federation-<SIDE>-upstream-ca\.volume:/var/lib/spire/upstream-ca:ro,Z|d"
      )
    fi
    _install_substituted "$server_tpl" \
        "${dst}/wakir-spire-server-federation-${side}.container" \
        "${server_sed_args[@]}" \
      || { log_err "install $server_tpl failed"; return 2; }

    install -d -m 755 /etc/wakir/spire-federation
    local server_conf_src=""
    case "$WAKIR_PILOT_MODE" in
      single-org)
        server_conf_src="${WAKIR_REPO_ROOT}/infra/spire/federation/config/spire-server-pilot-single-org.conf"
        ;;
      federation)
        server_conf_src="${WAKIR_REPO_ROOT}/infra/spire/federation/config/spire-server-${side}.conf"
        ;;
    esac
    # NOTE: the container's bind-mount target path stays
    # /etc/wakir/spire-federation/spire-server-${side}.conf in BOTH
    # modes — only the source file the bootstrap reads-from differs.
    # That preserves the existing test_pilot_bringup_substance.py
    # TV-BRINGUP-06 config-path invariant.
    if [[ -f "$server_conf_src" ]]; then
      local server_conf_dst="/etc/wakir/spire-federation/spire-server-${side}.conf"
      # Bug-28 fix: single-org server config is now
      # ``<TRUST_DOMAIN>``-tokenised (mirror of the Quadlet-template
      # substitution at L1269-1273). Use _install_substituted so the
      # tokens are replaced with the side-specific values at install
      # time. Federation variant has the trust_domain baked-in per
      # ``spire-server-${side}.conf`` so the substitution is a no-op
      # for that path — sed runs idempotent there.
      _install_substituted "$server_conf_src" "$server_conf_dst" \
          -e "s|<TRUST_DOMAIN>|${WAKIR_TRUST_DOMAIN}|g" \
        || { log_err "install $server_conf_src failed"; return 2; }
    else
      log_warn "${server_conf_src} not found in repo; skipping config install"
    fi
    log_ok "SPIRE-server-${side} unit installed (mode=${WAKIR_PILOT_MODE})"
  else
    log_warn "spire-server-federation.container not found at ${server_tpl}"
  fi

  # 6d. SPIRE-Agent-Federation container (per-side substitution).
  #
  # Bug 7 substance-fix: WAKIR_PILOT_MODE selects which
  # agent-config variant the bootstrap installs. In single-org mode
  # the agent template's federated-bundles read-only volume mount is
  # dropped (no peer exposes a bundles volume; the line would be a
  # dangling reference to a never-populated volume).
  local agent_tpl="${agent_src}/wakir-spire-agent-federation.container"
  if [[ -f "$agent_tpl" ]]; then
    local agent_sed_args=(
      -e "s|<SIDE>|${side}|g"
      -e "s|<TRUST_DOMAIN>|${WAKIR_TRUST_DOMAIN}|g"
      -e "s|<SERVER_DNS>|spire-server-${side}|g"
    )
    if [[ "$WAKIR_PILOT_MODE" == "single-org" ]]; then
      # Drop the federated-bundles read-only mount line. The
      # single-org agent has no peer bundles to ingest; the
      # ``insecure_bootstrap = true`` posture obtains the trust-anchor
      # via the server's gRPC handshake instead.
      agent_sed_args+=(
        -e "\|wakir-spire-server-federation-<SIDE>-bundles\.volume:/var/lib/spire/bundles:ro|d"
      )
    fi
    # Bug-40 corollary -- join-token round-trip. Step 6i
    # seds the ISSUED join-token into the installed unit, so the
    # installed file can never equal a freshly rendered template (which
    # carries ``WAKIR_JOIN_TOKEN_PLACEHOLDER``). Under the pre-Bug-40
    # "start only if stopped" logic that was invisible: every re-run
    # rewrote the unit back to the placeholder and the placeholder
    # version was simply never applied -- until the next VM reboot,
    # where systemd would start the agent with
    # ``-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER`` (the Bug-37
    # crash-loop, armed and waiting). With convergence the same rewrite
    # would restart the agent into that broken unit on EVERY run.
    #
    # Fix: carry the live token over into the render. A re-run then
    # produces a byte-identical file (no change signal, no restart),
    # and a genuine template change is rendered WITH the live token.
    local agent_quadlet_installed="${dst}/wakir-spire-agent-${side}.container"
    local carried_token
    carried_token="$(_carried_join_token "$agent_quadlet_installed")"
    if [[ -n "$carried_token" ]]; then
      agent_sed_args+=(
        -e "s|WAKIR_JOIN_TOKEN_PLACEHOLDER|${carried_token}|g"
      )
      log_note "carried live join-token into the agent-unit render (no spurious rewrite)"
    fi
    _install_substituted "$agent_tpl" \
        "$agent_quadlet_installed" \
        "${agent_sed_args[@]}" \
      || { log_err "install $agent_tpl failed"; return 2; }

    local agent_conf_src=""
    case "$WAKIR_PILOT_MODE" in
      single-org)
        agent_conf_src="${WAKIR_REPO_ROOT}/infra/spire/agent/config/spire-agent-pilot-single-org.conf"
        ;;
      federation)
        agent_conf_src="${WAKIR_REPO_ROOT}/infra/spire/agent/config/spire-agent-${side}.conf"
        ;;
    esac
    # NOTE: container bind-mount target path stays
    # /etc/wakir/spire-agent-${side}.conf in BOTH modes.
    if [[ -f "$agent_conf_src" ]]; then
      local agent_conf_dst="/etc/wakir/spire-agent-${side}.conf"
      # Bug-28 fix: single-org agent config is now
      # ``<TRUST_DOMAIN>``/``<SERVER_DNS>``-tokenised. Use
      # _install_substituted (idempotent on already-substituted
      # federation variants).
      _install_substituted "$agent_conf_src" "$agent_conf_dst" \
          -e "s|<TRUST_DOMAIN>|${WAKIR_TRUST_DOMAIN}|g" \
          -e "s|<SERVER_DNS>|spire-server-${side}|g" \
        || { log_err "install $agent_conf_src failed"; return 2; }
    else
      log_warn "${agent_conf_src} not found in repo"
    fi
    log_ok "SPIRE-agent-${side} unit installed (mode=${WAKIR_PILOT_MODE})"
  else
    log_warn "spire-agent-federation.container not found at ${agent_tpl}"
  fi

  # 6e. NATS container (idempotent install).
  if [[ -f "${quadlet_src}/wakir-nats.container" ]]; then
    local nats_dst="${dst}/wakir-nats.container"
    _install_if_changed "${quadlet_src}/wakir-nats.container" "$nats_dst" \
      || { log_err "install wakir-nats.container failed"; return 2; }
    log_ok "NATS unit installed"
  else
    log_warn "wakir-nats.container not found"
  fi

  # 6f. systemd daemon-reload (initial — so podman-system-generator
  # materialises the just-installed units before we touch volumes).
  if ! "$WAKIR_BOOTSTRAP_SYSTEMCTL" daemon-reload; then
    log_err "systemctl daemon-reload failed"
    return 2
  fi
  log_ok "systemctl daemon-reload"

  # 6g. Bug 2 substance-fix: chown the named-volume
  # backing directories to uid:gid 1000:1000 so the uid:1000 SPIRE
  # processes can write into them. Podman creates the named volumes
  # owned by root by default; the container processes are non-root
  # per Quadlet ``User=1000`` and would otherwise fail with
  # ``permission denied`` on first write (``agent-data.json``,
  # ``keys.json``, Workload-API socket bind). The five volumes touched:
  #   * wakir-spire-server-federation-${side}-data
  #   * wakir-spire-server-federation-${side}-sockets
  #   * wakir-spire-server-federation-${side}-bundles
  #   * wakir-spire-agent-${side}-data
  #   * wakir-spire-agent-${side}-sockets
  # We let Podman create the volumes first via ``podman volume create
  # --ignore`` (idempotent) and then chown their backing mount-point.
  #
  # Bug-21 substance-fix: the previous block swallowed
  # chown stderr via ``2>/dev/null`` and degraded a real failure to a
  # log_warn while still emitting the global ``OK normalised`` line.
  # On Bring-up-4 (AR Fred, 2026-05-14) the volumes stayed root-owned
  # (uid:gid 0:0) even though the bootstrap reported success — chown
  # silently failed and the SPIRE-Agent then crash-looped on first
  # write. Fix: surface chown stderr, hard-verify owner via stat, halt
  # the bootstrap with return-code 2 on mismatch.
  #
  # Bug-22 substance-fix: on Bring-up-5 (repository owner,
  # 2026-05-14 ~14:00 CEST) the bootstrap reported the Bug-21 OK
  # line (``stat-verified``) yet the SPIRE-Agent immediately crash-
  # looped with the Bug-20 ``permission denied`` symptom on
  # ``/var/lib/spire/agent/.probe``. Post-mortem ``ls -lnd`` on the
  # agent-data volume's ``_data`` showed owner ``0 0`` even though
  # ``stat`` had reported ``1000:1000`` ~2 seconds earlier in step 6g.
  # Re-running the same one-shot curl|bash without other changes
  # produced 6/6 PASS — a non-deterministic Time-of-Check-vs-Time-of-
  # Use race between step 6g's ``podman volume create --ignore`` +
  # chown and step 6h/6j's ``systemctl start`` (which triggers podman-
  # system-generator to reconcile the named volume against the
  # ``.volume`` Quadlet unit, in some Podman builds re-initialising
  # the volume's backing directory).
  #
  # The fix is defensive idempotence: the chown-and-verify pass is
  # extracted into ``_chown_volume_with_verify`` and re-applied
  # immediately before each ``systemctl start`` of a Quadlet container
  # that mounts a named volume (step 6h server-start, step 6j agent-
  # start + NATS-start). Robust against any race we have not yet
  # named: if the owner gets reset between step 6g and the service-
  # start, we observe it and re-chown before the container init runs.
  # If owner is already ``1000:1000`` the helper is a fast no-op.
  #
  # The WAKIR_BOOTSTRAP_DEBUG=1 env-var emits before/after stat lines
  # for each chown invocation (off by default — keeps production logs
  # clean; flip on for the next bring-up to capture the race).
  local v
  for v in \
      "wakir-spire-server-federation-${side}-data" \
      "wakir-spire-server-federation-${side}-sockets" \
      "wakir-spire-server-federation-${side}-bundles" \
      "wakir-spire-server-federation-${side}-upstream-ca" \
      "wakir-spire-agent-${side}-data" \
      "wakir-spire-agent-${side}-sockets"
  do
    "$WAKIR_BOOTSTRAP_PODMAN" volume create --ignore "$v" >/dev/null 2>&1 || true
    _chown_volume_with_verify "$v" "step-6g-initial" || return 2
  done
  log_ok "named-volume permissions normalised (uid:gid 1000:1000, stat-verified)"

  # 6g-bis (ADR-0076 step 2). The upstream CA root, BEFORE the server
  # starts. The server's ``UpstreamAuthority "disk"`` block reads
  # /var/lib/spire/upstream-ca/root.{crt,key} at start and at every
  # CSR; a server started without it does not fall back to being its
  # own root, it fails to configure the plugin.
  #
  # Federation mode only: ADR-0076 scopes UpstreamAuthority to the
  # three federation server configs, and the single-org install drops
  # the mount (see 6c). Generating a private key for a config that
  # does not reference it would be key material without a consumer,
  # which is its own kind of debt.
  if [[ "$WAKIR_PILOT_MODE" == "federation" ]]; then
    _ensure_upstream_ca_material "$side" || return 2
  else
    log_note "single-org mode: no UpstreamAuthority in this config, no root material created"
  fi

  # 6h. Start the server FIRST. The agent depends on a running server
  # for the join-token attestation handshake; starting them in
  # parallel from a single systemctl-start race-loop reliably loses
  # the first attestation attempt and forces a restart cycle.
  #
  # Bug-22 substance-fix: defensive re-chown of the
  # server's volume set IMMEDIATELY before systemctl start. Closes
  # the TOC-vs-TOU race window between step 6g's ad-hoc chown and
  # the podman-system-generator's volume reconciliation at service-
  # start. See helper rationale.
  local server_unit="wakir-spire-server-federation-${side}.service"
  # Bug-40 substance-fix: converge, do not "start if
  # stopped". _converge_service_unit starts a stopped unit, restarts a
  # running unit whose installed definition is not the one the
  # container was created from, and leaves an in-sync unit untouched.
  # The Bug-25 wait-for-active runs inside the helper on BOTH paths --
  # step 6i issues ``spire-server token generate`` against this server
  # immediately after and must not race its boot.
  _converge_service_unit "$server_unit" "server" || return 2

  # 6h-bis (ADR-0076 step 3). Stage the agent's bootstrap trust anchor
  # from the now-running server, before the agent is started.
  #
  # The agent configs have pointed ``trust_bundle_path`` at
  # /var/lib/spire/bundles/bootstrap.jwks since May. Nothing ever
  # wrote it. Measured 2026-09-22 on both VMs: the directory is empty
  # and has been since it was created. The agent ran off its own
  # bundle cache until the cache aged out under the 24h ca_ttl, and
  # then it stopped attesting without anyone noticing for 127 days.
  #
  # Federation mode only: the single-org agent config bootstraps
  # through the server handshake and its Quadlet does not even mount
  # the bundles volume (6d drops the line).
  if [[ "$WAKIR_PILOT_MODE" == "federation" ]]; then
    _install_anchor_stager || return 2
    _stage_bootstrap_anchor "$side" || return 2
  fi

  # 6i. Bug 1/15 substance-fix: single-org Phase-1b
  # pilots use the join-token node-attestor. Token generation is a
  # mandatory Operator-Hand step in the manual recipe; the
  # one-shot bootstrap automates it by issuing
  # ``spire-server token generate`` against the just-started server,
  # parsing the token value, and substituting it into the agent
  # Quadlet's ``Exec=`` line (replacing the literal placeholder
  # ``WAKIR_JOIN_TOKEN_PLACEHOLDER``). Re-run is safe: if the agent
  # is already attested, the token-generate + sed-substitute steps
  # are skipped.
  #
  # Bug-37 substance-fix (Live-VM-Acceptance
  # 2026-05-15 ~20:10-20:15 CEST operator diagnosis): the prior code
  # only ran the token-generate path for ``WAKIR_PILOT_MODE ==
  # single-org`` and replaced it with a placeholder-strip in
  # federation-mode (step 6j sed-delete). That created a CONFIG
  # COHERENCY DRIFT — the agent-config (spire-agent-<side>.conf)
  # still declared ``NodeAttestor "join_token"`` as the plugin while
  # the ExecStart line was stripped of the corresponding
  # ``-joinToken <token>`` arg. The agent crashed in an infinite
  # ``InvalidArgument: join token was not provided`` retry-loop and
  # never bound the workload-API socket.
  #
  # Root-cause fix: in federation-mode, generate + inject the token
  # using the same code-path as single-org. Each SPIRE-server attests
  # its OWN agent via join-token; cross-trust-domain federation is
  # the cross-bundle-exchange that runs OVER the bundle-endpoint
  # listener (port 8443) and the ``federates_with`` block, NOT over
  # NodeAttestation. The join-token NodeAttestor is the correct
  # primitive for federation-mode agent enrollment, identical to
  # single-org agent enrollment. The only federation-mode-specific
  # difference is the cross-bundle exchange between SPIRE-servers,
  # which is wired in spire-server-<side>.conf §federates_with and
  # is already covered by Bug-30..32 substance-fixes.
  #
  # Disagree-note: the Bug-37 brief recommended Option A
  # (x509pop) — "clean federation-attestation-pattern". Infra
  # disagree-note: x509pop is overkill for the wakir-orbit-VM-pair
  # federation pilot because (a) each SPIRE-server attests its OWN
  # agent, NOT the peer agent, so x509pop's cross-trust-domain cert
  # exchange is unused; (b) x509pop adds an Operator-Hand cert+key
  # provisioning step ahead of step-6 which expands the bring-up
  # surface; (c) join-token is the existing-pattern + minimal
  # delta. Identity-substrate cross-review (Reza-Cross-Review Zone-B; literal
  # pinned by tests/infra/test_pilot_bootstrap_bug_36_37_fixes.py) is mandatory pre-merge — if
  # it recommends x509pop on identity-substrate grounds, this fix
  # is one diff-block away from a clean rebase to that pattern.
  local agent_quadlet_dst="${dst}/wakir-spire-agent-${side}.container"
  local agent_already_attested=0
  if "$WAKIR_BOOTSTRAP_PODMAN" exec "wakir-spire-server-federation-${side}" \
       /opt/spire/bin/spire-server agent list 2>/dev/null \
       | grep -q "spiffe://${WAKIR_TRUST_DOMAIN}/${WAKIR_ORG_ID}/agent/pilot"; then
    agent_already_attested=1
    log_ok "agent already attested (skip join-token generate)"
  fi
  # Bug-40: the placeholder alone decides, not the
  # attestation state. An already-attested agent whose unit was
  # re-installed from the template carries the placeholder again; under
  # "start only if stopped" that stayed invisible, under convergence it
  # is a unit that must not be applied. Issuing a token that then goes
  # unused costs nothing (TTL 1h, one row in the datastore); leaving
  # the placeholder in an applied unit costs the agent.
  if [[ -f "$agent_quadlet_dst" ]] \
     && grep -q "WAKIR_JOIN_TOKEN_PLACEHOLDER" "$agent_quadlet_dst"; then
    local jt_spiffe="spiffe://${WAKIR_TRUST_DOMAIN}/${WAKIR_ORG_ID}/agent/pilot"
    local jt_raw="" jt_token=""
    jt_raw=$("$WAKIR_BOOTSTRAP_PODMAN" exec \
               "wakir-spire-server-federation-${side}" \
               /opt/spire/bin/spire-server token generate \
               -spiffeID "$jt_spiffe" \
               -ttl 3600 2>/dev/null || echo "")
    # Output form: "Token: <hex>"
    jt_token=$(printf '%s\n' "$jt_raw" \
               | sed -n 's/^Token:[[:space:]]*\(.*\)$/\1/p' \
               | head -1 | tr -d '[:space:]')
    if [[ -n "$jt_token" ]]; then
      sed -i "s|WAKIR_JOIN_TOKEN_PLACEHOLDER|${jt_token}|g" \
            "$agent_quadlet_dst" \
        || { log_err "join-token sed-substitute on ${agent_quadlet_dst} failed"; return 2; }
      log_ok "join-token issued for ${jt_spiffe} and injected into agent Quadlet (mode=${WAKIR_PILOT_MODE})"
      # Bug-40: the injection rewrote the agent unit --
      # register it so step 6j applies the unit instead of leaving a
      # running agent on the pre-injection definition.
      _note_config_change "$agent_quadlet_dst"
      # Daemon-reload so the regenerated Exec= line is picked up
      # before agent start.
      "$WAKIR_BOOTSTRAP_SYSTEMCTL" daemon-reload \
        || { log_err "post-token daemon-reload failed"; return 2; }
    else
      log_err "spire-server token generate produced no parseable token"
      log_note "diagnose: podman exec wakir-spire-server-federation-${side} /opt/spire/bin/spire-server token generate -spiffeID ${jt_spiffe} -ttl 3600"
      return 2
    fi
  elif [[ -f "$agent_quadlet_dst" ]]; then
    log_ok "join-token placeholder already substituted (no-op)"
  fi

  # 6j. Start the agent + NATS.
  #
  # Bug-37 substance-fix: federation-mode previously
  # stripped the join-token placeholder here (sed-delete on the
  # ExecStart line). That code-path created the Bug-37 config-
  # coherency drift. With step-6i now running for BOTH modes, the
  # agent Quadlet has a real injected token by the time we reach
  # step-6j; no mode-specific strip remains. If step-6i failed to
  # inject (e.g. token-generate produced no parseable output) the
  # bootstrap aborted there with rc=2; reaching this point implies
  # the placeholder is substituted.
  #
  # Config-coherency assertion: the agent-config file (mounted at
  # /etc/wakir/spire-agent-<side>.conf) declares NodeAttestor
  # ``join_token``; the ExecStart line carries the matching
  # ``-joinToken <hex>`` arg. Both modes now share the same
  # coherent config shape.

  # Bug-22 substance-fix: defensive re-chown of each
  # container's volume set IMMEDIATELY before its systemctl start.
  # ``server`` is handled in step 6h above; here we handle agent +
  # NATS. The kind-to-volume mapping lives in _pre_start_chown_sweep.
  local unit kind
  for unit in \
      "wakir-spire-agent-${side}.service" \
      "wakir-nats.service"
  do
    case "$unit" in
      "wakir-spire-agent-${side}.service") kind="agent" ;;
      "wakir-nats.service")                kind="nats"  ;;
      *)                                   kind=""      ;;
    esac
    # Bug-40: same convergence helper as step 6h. The
    # server -> agent order is preserved by the call order (6h before
    # 6j): the agent pulls its join-token from a running server, and a
    # server re-issue after the agent start loses the attestation.
    # The Bug-25 wait points (is-active, and the agent's Workload-API
    # socket) live inside the helper and therefore now also cover the
    # restart path -- a restart re-opens the same race as a cold start.
    _converge_service_unit "$unit" "$kind" || return 2
  done

  # 6k (ADR-0076 step 4). The re-staging timer.
  #
  # One staged anchor at bring-up time is the May half-life with extra
  # steps: ca_ttl stays at 24h by decision, so the signing
  # intermediate keeps rotating daily. 30 minutes is far enough inside
  # that window that a couple of missed ticks are survivable, and the
  # run costs one podman exec and one rename.
  #
  # This timer is itself a standing obligation, and this house has
  # just demonstrated what it does with those. It is named in the
  # acceptance probe for that reason -- a refresher nobody watches is
  # the next four months.
  if [[ "$WAKIR_PILOT_MODE" == "federation" ]]; then
    _install_restage_timer "$side" || return 2
  fi

  return 0
}

# ---------------------------------------------------------------------------
# Step 7: NATS-KV bucket init
# ---------------------------------------------------------------------------

step_7_bucket_init() {
  log_step 7 "$TOTAL_STEPS" "NATS-KV-Bucket-Init fuer Pilot-Org '${WAKIR_ORG_ID}'"

  install -d -m 755 /etc/wakir

  # Onboarded-orgs roster (idempotent append).
  local roster=/etc/wakir/onboarded-orgs
  if [[ ! -f "$roster" ]]; then
    cat > "$roster" <<EOF
# Wakir Phase-1b pilot -- onboarded organisations
${WAKIR_ORG_ID}
EOF
    log_ok "wrote ${roster}"
  else
    if ! grep -qx "${WAKIR_ORG_ID}" "$roster"; then
      echo "${WAKIR_ORG_ID}" >> "$roster"
      log_ok "appended ${WAKIR_ORG_ID} to ${roster}"
    else
      log_ok "${WAKIR_ORG_ID} already in ${roster}"
    fi
  fi

  # Bucket-init env file (idempotent create with 0600).
  local envf=/etc/wakir/nats-kv-bucket-init.env
  if [[ ! -f "$envf" ]]; then
    install -m 600 /dev/null "$envf"
    cat > "$envf" <<'EOF'
# Phase-1b: open-token, no auth. Phase-3: SPIFFE-JWT-SVID.
WAKIR_NATS_TOKEN=
EOF
    log_ok "wrote ${envf} (mode 0600)"
  else
    log_ok "${envf} already present"
  fi

  # Install + start the bucket-init Quadlet unit.
  local src="${WAKIR_REPO_ROOT}/quadlet/wakir-nats-kv-bucket-init.container"
  local dst=/etc/containers/systemd/wakir-nats-kv-bucket-init.container
  if [[ ! -f "$src" ]]; then
    log_err "bucket-init unit source not found: ${src}"
    return 2
  fi
  # substance-fix (Bug-18, live bring-up bug report 2026-05-14):
  # daemon-reload MUST fire unconditionally after the install-or-skip
  # block, BEFORE the systemctl start. Live-Bring-up-3 observed
  # ``Warning: The unit file ... changed on disk. Run 'systemctl
  # daemon-reload' to reload units.`` because the reload only ran on
  # the install branch — a re-run where dst already existed but
  # bytewise differed (operator-hand patch landed between bring-ups)
  # would skip the reload and systemd would keep the stale unit cache.
  # Mirrors Phase-6's discipline (Z. 6f / 6i / 6j: daemon-reload after
  # every Quadlet rewrite).
  if ! cmp -s "$src" "$dst" 2>/dev/null; then
    install -m 644 "$src" "$dst" \
      || { log_err "install bucket-init unit failed"; return 2; }
    log_ok "bucket-init unit installed (or refreshed)"
  else
    log_ok "bucket-init unit already up-to-date"
  fi
  "$WAKIR_BOOTSTRAP_SYSTEMCTL" daemon-reload \
    || { log_err "daemon-reload after bucket-init install failed"; return 2; }
  log_ok "systemctl daemon-reload"

  # One-shot: start, then verify in journal.
  "$WAKIR_BOOTSTRAP_SYSTEMCTL" start wakir-nats-kv-bucket-init.service \
    || { log_err "bucket-init service start failed"; return 2; }
  log_ok "bucket-init service started (one-shot)"

  return 0
}

# ---------------------------------------------------------------------------
# Step 8: Smoke test
# ---------------------------------------------------------------------------

step_8_smoke() {
  # Bug-29 fix: smoke is side-aware (since PR #53), but
  # the bootstrap forgot to pass --side and so the smoke probe always
  # checked the ``wakir``-side units. On the orbit-side VM that yielded
  # a deterministic FAIL because the wakir-side units do not exist
  # there. Forward WAKIR_SIDE explicitly. side="wakir" matches the
  # pre-PR-53 default smoke behaviour so existing single-VM (pilot)
  # smoke continues to work unchanged.
  local side="${WAKIR_SIDE:-wakir}"
  # Bug-38 fix: in federation-mode the smoke CLI's two
  # substance checks (federation-bundle-sync-reachable +
  # federation-cross-trust-domain-verify) are gated on
  # WAKIR_FEDERATION_MODE=enabled AND --peer-side. The bootstrap KNOWS
  # both pieces here (mode=federation + WAKIR_PEER_SIDE), so wire them
  # through automatically. In single-org-mode the smoke runs unchanged
  # (no peer-side, no env-var, both gates stay SKIP).
  local smoke_args=(--org "$WAKIR_ORG_ID" --side "$side")
  local smoke_env=()
  if [[ "$WAKIR_PILOT_MODE" == "federation" && -n "${WAKIR_PEER_SIDE:-}" ]]; then
    smoke_args+=(--peer-side "$WAKIR_PEER_SIDE")
    smoke_env+=(WAKIR_FEDERATION_MODE=enabled)
    log_step 8 "$TOTAL_STEPS" "Smoke-Test (proxmox-bringup-smoke --org ${WAKIR_ORG_ID} --side ${side} --peer-side ${WAKIR_PEER_SIDE}; WAKIR_FEDERATION_MODE=enabled)"
  else
    log_step 8 "$TOTAL_STEPS" "Smoke-Test (proxmox-bringup-smoke --org ${WAKIR_ORG_ID} --side ${side})"
  fi

  local smoke="${WAKIR_BOOTSTRAP_SMOKE:-${WAKIR_REPO_ROOT}/bin/proxmox-bringup-smoke}"
  if [[ ! -x "$smoke" ]]; then
    log_err "smoke binary not found or not executable: ${smoke}"
    return 2
  fi

  if env "${smoke_env[@]}" "$smoke" "${smoke_args[@]}"; then
    log_ok "smoke: all checks PASS"
    return 0
  fi
  log_err "smoke: at least one check FAIL"
  return 2
}

# ---------------------------------------------------------------------------
# Step 15 (optional, Bug-39 Option-A substrate):
# Bilateral-Federation-Handshake-Precheck.
# ---------------------------------------------------------------------------
#
# Bug-39 is the asymmetric-pilot-topology question: wakir-pilot runs in
# single-org-mode (one pilot-persona container, V2-Anchor, no peer),
# while wakir-orbit runs in federation-mode against wakir-pilot. The
# Cross-VM-Federation smoke-test (proxmox-bringup-smoke 8/8 with the
# federation gates) requires BOTH sides to be in federation-mode.
#
# Two options were considered:
#
#   Option A — Pilot-Symmetric: bring wakir-pilot into federation-mode
#              as well. Risk: the running pilot-persona container
#              needs a re-spawn after the mode-switch because the
#              SPIRE-server-federation-${side}.service is a different
#              unit name and the SPIFFE-ID under federation-mode is
#              spiffe://wakir.test/spire/agent/${side}/... — the
#              workload-API socket re-binds with a new SPIFFE-ID and
#              the persona-engine inside the container has to
#              re-authenticate.
#
#   Option B — Production-Setup-Item: park Bug-39 as a
#              Phase-3 Production-rollout item. Both VMs flip to
#              federation-mode in a single coordinated Operator-Hand
#              window; the Pilot-Phase Doppelbetrieb-shadow tolerates
#              the asymmetry until then.
#
# The operator decides which variant goes live. This bootstrap ships
# **both substrates** so the decision can be made at run-time without
# a source-patch:
#
#   - The Option-A path is gated on WAKIR_BILATERAL_PRECHECK=1. When
#     set, step_15 runs AFTER step_8_smoke and verifies the prereqs
#     for the bilateral switch (peer-VM reachable, peer-side already
#     in federation-mode, persona-container re-spawn-window declared).
#     The precheck does NOT mutate the running VM; it produces a
#     PASS/FAIL summary that the Operator-Hand uses as the
#     go/no-go gate for the actual mode-flip + container re-spawn
#     (which stays Operator-Hand because the re-spawn touches the
#     persona-engine state-pack).
#
#   - The Option-B path is the default (WAKIR_BILATERAL_PRECHECK unset
#     or 0). step_15 is skipped silently; the Doppelbetrieb-shadow
#     keeps running on the asymmetric topology.
#
# Decision-record: docs/decisions/topology-bilateral-federation.md
# captures the full topology-decision rationale for AR review.

step_15_bilateral_precheck() {
  if [[ "${WAKIR_BILATERAL_PRECHECK:-0}" != "1" ]]; then
    return 0
  fi
  log_step 15 15 "Bilateral-Federation-Handshake-Precheck (Bug-39 Option-A substrate)"

  # Precheck 15a: this side must already be in federation-mode (the
  # precheck only makes sense AFTER the bootstrap has flipped this VM
  # over). Single-org-mode here means the operator forgot to set
  # WAKIR_PILOT_MODE=federation; the precheck would always FAIL.
  if [[ "$WAKIR_PILOT_MODE" != "federation" ]]; then
    log_err "bilateral-precheck requires WAKIR_PILOT_MODE=federation on this side; got '${WAKIR_PILOT_MODE}'"
    log_err "did you forget to set WAKIR_PILOT_MODE=federation in the bilateral-flip env?"
    return 2
  fi

  # Precheck 15b: peer-side + peer-host must be set. Without them the
  # cross-VM TCP reach + bundle-endpoint probe cannot run.
  if [[ -z "${WAKIR_PEER_SIDE:-}" || -z "${WAKIR_PEER_HOST:-}" ]]; then
    log_err "bilateral-precheck requires WAKIR_PEER_SIDE + WAKIR_PEER_HOST"
    return 2
  fi

  # Precheck 15c: peer bundle-endpoint reachable on TCP 8443. We do
  # NOT validate the SPIFFE-bundle handshake here (that is the smoke-
  # test's job); we only verify that the peer's bundle-endpoint
  # listener is bound and reachable — i.e. the peer-side is already
  # in federation-mode itself. This is the bilateral-handshake
  # precondition that Bug-39 surfaced.
  if ! timeout 5 bash -c \
       "exec 3<>/dev/tcp/${WAKIR_PEER_HOST}/8443" 2>/dev/null; then
    log_err "peer ${WAKIR_PEER_HOST}:8443 not reachable — peer-side may not be in federation-mode"
    log_err "bilateral-precheck FAIL: complete the peer-side bootstrap"
    log_err "with WAKIR_PILOT_MODE=federation first, THEN re-run this side"
    log_err "with WAKIR_BILATERAL_PRECHECK=1."
    return 2
  fi
  log_ok "  - peer ${WAKIR_PEER_HOST}:8443: TCP reachable (peer in federation-mode)"

  # Precheck 15d: persona-container re-spawn-window declared. The
  # mode-flip on this side invalidates the running persona-engine's
  # workload-API socket (new SPIFFE-ID); the operator MUST have
  # declared a re-spawn-window via WAKIR_PERSONA_RESPAWN_WINDOW so
  # the operational invariant is captured in the bring-up log.
  if [[ -z "${WAKIR_PERSONA_RESPAWN_WINDOW:-}" ]]; then
    log_warn "WAKIR_PERSONA_RESPAWN_WINDOW not declared; persona-engine"
    log_warn "re-spawn after mode-flip will be unscheduled (operator-judgement)."
    log_warn "set WAKIR_PERSONA_RESPAWN_WINDOW='YYYY-MM-DD HH:MM CEST' to"
    log_warn "capture the planned re-spawn-window in the bring-up log."
  else
    log_ok "  - persona re-spawn-window declared: ${WAKIR_PERSONA_RESPAWN_WINDOW}"
  fi

  log_ok "bilateral-precheck PASS — ready for Operator-Hand mode-flip + persona re-spawn"
  return 0
}

# ---------------------------------------------------------------------------
# Main driver
# ---------------------------------------------------------------------------

main() {
  local steps=(
    "step_1_preflight"
    "step_2_toolbox"
    "step_3_cli_tools"
    "step_4_repo_clone"
    "step_5_image_pins"
    "step_6_quadlet"
    "step_7_bucket_init"
    "step_8_smoke"
  )

  local i
  for i in $(seq 1 "$TOTAL_STEPS"); do
    if [[ "$i" -lt "$RESUME_FROM" ]]; then
      printf '%s[%d/%d]%s SKIP (--resume-from %d)\n' \
        "$_BOLD" "$i" "$TOTAL_STEPS" "$_RESET" "$RESUME_FROM"
      continue
    fi
    local fn="${steps[$((i-1))]}"
    if ! "$fn"; then
      fail_step "$i" "${fn} failed"
    fi
  done

  # Bug-39 Option-A substrate: optional bilateral-
  # federation-handshake-precheck post-step. No-op unless
  # WAKIR_BILATERAL_PRECHECK=1; see the step_15_bilateral_precheck
  # header for the full Option-A vs Option-B decision-rationale.
  step_15_bilateral_precheck || fail_step 15 "step_15_bilateral_precheck failed"

  cat <<EOF

${_GREEN}${_BOLD}Wakir-Pilot-VM bring-up complete.${_RESET}

  Org-ID:        ${WAKIR_ORG_ID}
  Trust-Domain:  ${WAKIR_TRUST_DOMAIN}

  Next-step suggestions:
    sudo journalctl -u 'wakir-*.service' -f
    sudo ${WAKIR_REPO_ROOT}/bin/proxmox-bringup-smoke --org ${WAKIR_ORG_ID}

  For a Proxmox snapshot of this clean state:
    qm snapshot <vmid> post-bring-up-clean --description "Smoke ok"

EOF
}

# Only auto-run main when the script is
# executed directly. Sourcing the script (e.g. from a hermetic test
# that wants to invoke a single function like _install_peer_host_entry)
# must NOT trigger the full bring-up flow. The ``BASH_SOURCE`` check
# follows the standard ``main-gate`` pattern used by Bash idioms.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
