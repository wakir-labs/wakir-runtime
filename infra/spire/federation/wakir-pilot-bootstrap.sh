#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-9 Tag-3 — One-Shot Wakir-Pilot-VM Bring-up.
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
#   WAKIR_TRUST_DOMAIN        default: wakir.test
#   WAKIR_REPO_BRANCH         default: main
#   WAKIR_REPO_URL            default: https://github.com/wakir-labs/wakir-runtime.git
#   WAKIR_REPO_ROOT           default: /opt/wakir-runtime
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
# -- Kai

set -u

# ---------------------------------------------------------------------------
# Configuration / defaults
# ---------------------------------------------------------------------------

PROG=$(basename "$0")
TOTAL_STEPS=8
RESUME_FROM=1

: "${WAKIR_ORG_ID:=acme}"
: "${WAKIR_TRUST_DOMAIN:=wakir.test}"
: "${WAKIR_REPO_BRANCH:=main}"
: "${WAKIR_REPO_URL:=https://github.com/wakir-labs/wakir-runtime.git}"
: "${WAKIR_REPO_ROOT:=/opt/wakir-runtime}"
: "${WAKIR_SKIP_COSIGN_VERIFY:=0}"
: "${WAKIR_SKIP_PROMPTS:=0}"
: "${COSIGN_VERSION:=v2.4.1}"

# Test-injection hooks. In production these expand to nothing; the
# hermetic test surface in tests/infra/test_pilot_bootstrap.py can
# point these at fixtures.
: "${WAKIR_BOOTSTRAP_PODMAN:=podman}"
: "${WAKIR_BOOTSTRAP_SYSTEMCTL:=systemctl}"
: "${WAKIR_BOOTSTRAP_CURL:=curl}"
: "${WAKIR_BOOTSTRAP_GIT:=git}"
: "${WAKIR_BOOTSTRAP_SMOKE:=}"   # if empty, derived from REPO_ROOT
: "${WAKIR_BOOTSTRAP_TOOLBOX:=toolbox}"

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
  log_err "$msg"
  cat <<EOF >&2

${_RED}${_BOLD}Bring-up halted at step ${step_n}.${_RESET}

  Resume after fixing the issue:
    sudo bash ${PROG} --resume-from ${step_n}

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
  WAKIR_TRUST_DOMAIN        (default: wakir.test)
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
  Repo-Branch:   ${WAKIR_REPO_BRANCH}
  Repo-Root:     ${WAKIR_REPO_ROOT}
  Resume-From:   ${RESUME_FROM}/${TOTAL_STEPS}
EOF

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

step_4_repo_clone() {
  log_step 4 "$TOTAL_STEPS" "Repo klonen nach ${WAKIR_REPO_ROOT}"

  if [[ -d "${WAKIR_REPO_ROOT}/.git" ]]; then
    log_ok "repo already present; fetching latest on ${WAKIR_REPO_BRANCH}"
    (
      cd "$WAKIR_REPO_ROOT"
      "$WAKIR_BOOTSTRAP_GIT" fetch --depth 1 origin "$WAKIR_REPO_BRANCH" \
        >/dev/null 2>&1
      "$WAKIR_BOOTSTRAP_GIT" checkout "$WAKIR_REPO_BRANCH" >/dev/null 2>&1
      "$WAKIR_BOOTSTRAP_GIT" reset --hard "origin/${WAKIR_REPO_BRANCH}" \
        >/dev/null 2>&1
    ) || { log_err "git fetch/reset failed"; return 2; }
    log_ok "repo updated to origin/${WAKIR_REPO_BRANCH}"
    return 0
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
  return 0
}

# ---------------------------------------------------------------------------
# Step 5: Image-pin resolve
# ---------------------------------------------------------------------------

step_5_image_pins() {
  log_step 5 "$TOTAL_STEPS" "Image-Pin-Resolve via cosign + skopeo (3 Images)"

  if [[ "$WAKIR_SKIP_COSIGN_VERIFY" == "1" ]]; then
    log_warn "WAKIR_SKIP_COSIGN_VERIFY=1; images run with tag reference only"
    log_warn "for production-use unset the flag and re-run --resume-from 5"
    return 0
  fi

  local resolver="${WAKIR_REPO_ROOT}/infra/spire/federation/proxmox/resolve-image-pins.sh"
  if [[ ! -x "$resolver" ]]; then
    log_err "resolver not found: ${resolver}"
    return 2
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
  for image in \
      ghcr.io/spiffe/spire-server:1.14.6 \
      ghcr.io/spiffe/spire-agent:1.14.6 \
      docker.io/library/python:3.13-slim
  do
    log_note "cosign + skopeo cross-check: ${image}"

    local cosign_digest=""
    local skopeo_digest=""

    # cosign verify (only for SPIRE; python:3.13-slim is on DockerHub
    # without Sigstore signing as of 2026-05-13 -- IMAGE_PINS.md §2.4).
    if [[ "$image" == ghcr.io/spiffe/* ]]; then
      cosign_digest=$(cosign verify \
        --certificate-identity-regexp 'https://github\.com/spiffe/spire/' \
        --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
        "$image" 2>/dev/null \
        | jq -r '.[0].critical.image."docker-manifest-digest" // empty' \
        || echo "")
      if [[ -z "$cosign_digest" ]]; then
        log_err "cosign verify failed or produced empty digest for ${image}"
        return 2
      fi
    fi

    # skopeo inspect (cross-check OR primary for DockerHub).
    skopeo_digest=$(skopeo inspect "docker://${image}" 2>/dev/null \
      | jq -r '.Digest // empty' || echo "")
    if [[ -z "$skopeo_digest" ]]; then
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

  "$resolver" \
    --spire-server-digest "${digests["ghcr.io/spiffe/spire-server:1.14.6"]}" \
    --spire-agent-digest  "${digests["ghcr.io/spiffe/spire-agent:1.14.6"]}" \
    --python-digest       "${digests["docker.io/library/python:3.13-slim"]}" \
    --root                "$WAKIR_REPO_ROOT" \
    --apply \
    || { log_err "resolve-image-pins.sh --apply failed"; return 2; }

  log_ok "image-pin resolve applied"
  return 0
}

# ---------------------------------------------------------------------------
# Step 6: Quadlet units
# ---------------------------------------------------------------------------

step_6_quadlet() {
  log_step 6 "$TOTAL_STEPS" "Quadlet-Units installieren (Networks, Volumes, SPIRE, NATS)"

  local quadlet_src="${WAKIR_REPO_ROOT}/quadlet"
  local fed_src="${WAKIR_REPO_ROOT}/infra/spire/federation/quadlet"
  local agent_src="${WAKIR_REPO_ROOT}/infra/spire/agent/quadlet"
  local dst="/etc/containers/systemd"
  local side="wakir"

  if [[ ! -d "$quadlet_src" ]]; then
    log_err "quadlet source not found: ${quadlet_src}"
    return 2
  fi

  # 6a. Networks
  local f
  for f in \
      "${quadlet_src}/wakir-orchestrator.network" \
      "${fed_src}/wakir-federation.network"
  do
    if [[ -f "$f" ]]; then
      install -m 644 "$f" "$dst/$(basename "$f")" \
        || { log_err "install $f failed"; return 2; }
    fi
  done
  log_ok "network units installed"

  # 6b. Volumes (with per-side substitution where the template uses <SIDE>)
  local v
  for v in \
      "${quadlet_src}"/*.volume \
      "${fed_src}"/*.volume \
      "${agent_src}"/*.volume
  do
    [[ -f "$v" ]] || continue
    local base
    base=$(basename "$v" | sed "s/<SIDE>/${side}/g")
    sed -e "s/<SIDE>/${side}/g" "$v" > "${dst}/${base}" \
      || { log_err "install $v failed"; return 2; }
    chmod 644 "${dst}/${base}"
  done
  log_ok "volume units installed"

  # 6c. SPIRE-Server-Federation container (per-side substitution)
  local server_tpl="${fed_src}/wakir-spire-server-federation.container"
  if [[ -f "$server_tpl" ]]; then
    sed -e "s/<SIDE>/${side}/g" \
        -e "s/<HOST_BUNDLE_PORT>/8443/g" \
        -e "s/<HOST_GRPC_PORT>/8082/g" \
        "$server_tpl" \
        > "${dst}/wakir-spire-server-federation-${side}.container" \
      || { log_err "install $server_tpl failed"; return 2; }
    chmod 644 "${dst}/wakir-spire-server-federation-${side}.container"

    install -d -m 755 /etc/wakir/spire-federation
    local server_conf="${WAKIR_REPO_ROOT}/infra/spire/federation/config/spire-server-${side}.conf"
    if [[ -f "$server_conf" ]]; then
      install -m 644 "$server_conf" "/etc/wakir/spire-federation/spire-server-${side}.conf"
    else
      log_warn "spire-server-${side}.conf not found in repo; skipping config install"
    fi
    log_ok "SPIRE-server-${side} unit installed"
  else
    log_warn "spire-server-federation.container not found at ${server_tpl}"
  fi

  # 6d. SPIRE-Agent-Federation container (per-side substitution)
  local agent_tpl="${agent_src}/wakir-spire-agent-federation.container"
  if [[ -f "$agent_tpl" ]]; then
    sed -e "s|<SIDE>|${side}|g" \
        -e "s|<TRUST_DOMAIN>|${WAKIR_TRUST_DOMAIN}|g" \
        -e "s|<SERVER_DNS>|spire-server-${side}|g" \
        "$agent_tpl" \
        > "${dst}/wakir-spire-agent-${side}.container" \
      || { log_err "install $agent_tpl failed"; return 2; }
    chmod 644 "${dst}/wakir-spire-agent-${side}.container"

    local agent_conf="${WAKIR_REPO_ROOT}/infra/spire/agent/config/spire-agent-${side}.conf"
    if [[ -f "$agent_conf" ]]; then
      install -m 644 "$agent_conf" "/etc/wakir/spire-agent-${side}.conf"
    else
      log_warn "spire-agent-${side}.conf not found in repo"
    fi
    log_ok "SPIRE-agent-${side} unit installed"
  else
    log_warn "spire-agent-federation.container not found at ${agent_tpl}"
  fi

  # 6e. NATS container
  if [[ -f "${quadlet_src}/wakir-nats.container" ]]; then
    install -m 644 "${quadlet_src}/wakir-nats.container" \
      "${dst}/wakir-nats.container" \
      || { log_err "install wakir-nats.container failed"; return 2; }
    log_ok "NATS unit installed"
  else
    log_warn "wakir-nats.container not found"
  fi

  # 6f. systemd daemon-reload, then start the units in dependency order.
  if ! "$WAKIR_BOOTSTRAP_SYSTEMCTL" daemon-reload; then
    log_err "systemctl daemon-reload failed"
    return 2
  fi
  log_ok "systemctl daemon-reload"

  local unit
  for unit in \
      "wakir-spire-server-federation-${side}.service" \
      "wakir-spire-agent-${side}.service" \
      "wakir-nats.service"
  do
    # Idempotent start: only act if not already active.
    if "$WAKIR_BOOTSTRAP_SYSTEMCTL" is-active --quiet "$unit"; then
      log_ok "${unit} already active"
      continue
    fi
    if ! "$WAKIR_BOOTSTRAP_SYSTEMCTL" start "$unit"; then
      log_err "systemctl start ${unit} failed"
      return 2
    fi
    log_ok "${unit} started"
  done

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
  if ! cmp -s "$src" "$dst" 2>/dev/null; then
    install -m 644 "$src" "$dst" \
      || { log_err "install bucket-init unit failed"; return 2; }
    "$WAKIR_BOOTSTRAP_SYSTEMCTL" daemon-reload \
      || { log_err "daemon-reload failed"; return 2; }
    log_ok "bucket-init unit installed (or refreshed)"
  fi

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
  log_step 8 "$TOTAL_STEPS" "Smoke-Test (proxmox-bringup-smoke --org ${WAKIR_ORG_ID})"

  local smoke="${WAKIR_BOOTSTRAP_SMOKE:-${WAKIR_REPO_ROOT}/bin/proxmox-bringup-smoke}"
  if [[ ! -x "$smoke" ]]; then
    log_err "smoke binary not found or not executable: ${smoke}"
    return 2
  fi

  if "$smoke" --org "$WAKIR_ORG_ID"; then
    log_ok "smoke: 6/6 checks PASS"
    return 0
  fi
  log_err "smoke: at least one check FAIL"
  return 2
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

main "$@"
