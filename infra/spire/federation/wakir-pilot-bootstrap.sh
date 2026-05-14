#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
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
#   WAKIR_PILOT_MODE          default: single-org  (Sprint-9-Tag-5
#                             Bug 7 substance-fix: choose between
#                             ``single-org`` Phase-1b pilot config
#                             variants and ``federation`` dual-side
#                             Phase-2.1 variants. Single-org is the
#                             default — Phase-1b pilot does not have
#                             a federation peer; using the federation
#                             configs in single-org mode crashes the
#                             SPIRE-Server on partner-peer-DNS-miss.)
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

# Resolve a stable script reference for resume hints. When the bootstrap
# is invoked via `curl ... | sudo bash`, $0 collapses to ``bash`` and a
# naive ${PROG} reference would print `sudo bash bash --resume-from N`
# (Sprint-9-Tag-4 Bug 1). After step 4 the repo is on disk at
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
: "${WAKIR_REPO_BRANCH:=main}"
: "${WAKIR_REPO_URL:=https://github.com/wakir-labs/wakir-runtime.git}"
: "${WAKIR_REPO_ROOT:=/opt/wakir-runtime}"
: "${WAKIR_SKIP_COSIGN_VERIFY:=0}"
: "${WAKIR_SKIP_PROMPTS:=0}"
: "${COSIGN_VERSION:=v2.4.1}"

# Sprint-9-Tag-5 Bug 7 substance-fix: single-org pilot mode toggles the
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
#                   (Sprint-8 Tag-1/Tag-2 dual-side variants; requires
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
  WAKIR_TRUST_DOMAIN        (default: wakir.test)
  WAKIR_PILOT_MODE          (default: single-org; alt: federation)
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
  Pilot-Mode:    ${WAKIR_PILOT_MODE}
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

  # 1g. Sprint-9 Tag-7 substance-fix (Bug-16, Mira-Bug-Bilanz
  # 2026-05-14): explicit CLI-dependency check. Live-Bring-up-3 from-
  # scratch on Fedora-CoreOS revealed that the Step-5 image-pin
  # resolver relied on ``perl`` which is NOT on the FCOS host PATH.
  # The resolver silent-fell-through, the placeholder ``DIGEST_
  # PENDING_TOMAS_REVIEW`` remained in the bucket-init Quadlet, and
  # Step 7 crashed with ``invalid reference format``. The Tag-7
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
  log_step 5 "$TOTAL_STEPS" "Image-Pin-Resolve via cosign + skopeo (4 Images)"

  # Sprint-9-Tag-6 Bug 4 substance-fix: when ``WAKIR_SKIP_COSIGN_VERIFY=1``
  # is set, the previous form returned immediately without resolving the
  # ``wakir-provisioner`` digest. The bucket-init Quadlet then started
  # with the literal ``DIGEST_PENDING_TOMAS_REVIEW`` placeholder in its
  # ``Image=`` line and Podman refused the pull. The fix: in skip-cosign
  # mode, fall through to a skopeo-only resolution path for the
  # provisioner image (DockerHub-style digest fetch) and pass it via the
  # ``--wakir-provisioner-digest`` flag to the resolver. The SPIRE-server,
  # SPIRE-agent and python-base images skipped in this branch keep their
  # tag-only references (DEV / quick-pilot posture).
  local resolver="${WAKIR_REPO_ROOT}/infra/spire/federation/proxmox/resolve-image-pins.sh"
  if [[ ! -x "$resolver" ]]; then
    log_err "resolver not found: ${resolver}"
    return 2
  fi

  if [[ "$WAKIR_SKIP_COSIGN_VERIFY" == "1" ]]; then
    log_warn "WAKIR_SKIP_COSIGN_VERIFY=1; SPIRE + python images run with tag reference only"
    local prov_image="ghcr.io/wakir-labs/wakir-provisioner:0.1.2"
    log_note "skopeo-only resolve for ${prov_image} (cosign skipped)"
    local prov_digest=""
    prov_digest=$(skopeo inspect "docker://${prov_image}" 2>/dev/null \
      | jq -r '.Digest // empty' || echo "")
    if [[ -n "$prov_digest" ]]; then
      "$resolver" \
        --wakir-provisioner-digest "$prov_digest" \
        --root "$WAKIR_REPO_ROOT" \
        --apply \
        || { log_err "resolve-image-pins.sh --apply (provisioner-only) failed"; return 2; }
      log_ok "${prov_image} -> ${prov_digest} (skopeo-only)"
    else
      log_warn "skopeo inspect failed for ${prov_image}; bucket-init Quadlet keeps placeholder"
      log_warn "for production-use unset WAKIR_SKIP_COSIGN_VERIFY and re-run --resume-from 5"
    fi
    return 0
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
  # Sprint-9 Tag-4: wakir-provisioner is OPTIONAL on first bring-up
  # because the image may not yet be published. The loop tries it
  # last; a skopeo-failure for wakir-provisioner is non-fatal and
  # falls back to the placeholder-retain path (the Quadlet will not
  # start the bucket-init service until Operator-Hand re-resolves).
  # Sprint-9-Tag-6 Bug 4 substance-fix: bump the wakir-provisioner tag
  # from 0.1.0 to 0.1.2 (the BSL-1.1 relicensed image; AR-Decision
  # 2026-05-13). 0.1.0 carried four wheels (nats-py + cryptography +
  # rfc8785 + jsonschema); 0.1.2 carries nats-py only post-Reza-PR #33
  # Wirelang-Import-Disentanglement. The bucket-init Quadlet (Image=
  # ghcr.io/wakir-labs/wakir-provisioner:0.1.2@sha256:DIGEST_...) is
  # the single consumer of this digest.
  for image in \
      ghcr.io/spiffe/spire-server:1.14.6 \
      ghcr.io/spiffe/spire-agent:1.14.6 \
      docker.io/library/python:3.13-slim \
      ghcr.io/wakir-labs/wakir-provisioner:0.1.2
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
        log_err "cosign verify failed or produced empty digest for ${image}"
        return 2
      fi
    elif [[ "$image" == ghcr.io/wakir-labs/wakir-provisioner:* ]]; then
      cosign_digest=$(cosign verify \
        --certificate-identity-regexp 'https://github\.com/wakir-labs/wakir-runtime/' \
        --certificate-oidc-issuer 'https://token.actions.githubusercontent.com' \
        "$image" 2>/dev/null \
        | jq -r '.[0].critical.image."docker-manifest-digest" // empty' \
        || echo "")
      if [[ -z "$cosign_digest" ]]; then
        # Sprint-9 Tag-4: image may not yet be published on first
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
  if [[ -n "${digests["ghcr.io/wakir-labs/wakir-provisioner:0.1.2"]:-}" ]]; then
    resolver_args+=(
      --wakir-provisioner-digest "${digests["ghcr.io/wakir-labs/wakir-provisioner:0.1.2"]}"
    )
  else
    log_note "skipping wakir-provisioner pin (image not yet resolvable; bucket-init service will not start until Operator-Hand re-runs the resolver)"
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
# Quadlet container that mounts the volume (Bug-22 Tag-9 substance
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
      # Mirror of wakir-nats.container Volume= line. NATS runs as
      # uid:1000 too (compose parity). The bucket-init service is a
      # one-shot client and does not mount its own volume.
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

  # Helper: install $1 (source) to $2 (dest), substituting <SIDE>
  # and other tokens in the file CONTENT. Skipped (idempotent) when
  # dest already matches the source-after-substitution. Sprint-9-Tag-4
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
    if [[ -f "$target" ]] && cmp -s "$tmp" "$target"; then
      rm -f "$tmp"
      return 0
    fi
    install -m 644 "$tmp" "$target" || { rm -f "$tmp"; return 1; }
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
      if [[ -f "$target" ]] && cmp -s "$f" "$target"; then
        continue
      fi
      install -m 644 "$f" "$target" \
        || { log_err "install $f failed"; return 2; }
    fi
  done
  log_ok "network units installed"

  # 6b. Volumes (with per-side substitution).
  #
  # Sprint-9-Tag-4 Bug 2: source filenames in the federation/agent
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
    if [[ -f "$target" ]] && cmp -s "$v" "$target"; then
      continue
    fi
    install -m 644 "$v" "$target" \
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
    dest_base=$(printf '%s' "$base" \
      | sed "s/^wakir-spire-server-federation-\(data\|sockets\|bundles\)\.volume$/wakir-spire-server-federation-${side}-\1.volume/")
    if [[ "$dest_base" == "$base" ]] \
       && ! [[ "$base" =~ ^wakir-spire-server-federation-(data|sockets|bundles)\.volume$ ]]; then
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
  # Sprint-9-Tag-5 Bug 7 substance-fix: WAKIR_PILOT_MODE selects which
  # server-config variant the bootstrap installs.
  #   * single-org -> spire-server-pilot-single-org.conf
  #   * federation -> spire-server-${side}.conf
  # See top-of-file rationale block at WAKIR_PILOT_MODE definition.
  local server_tpl="${fed_src}/wakir-spire-server-federation.container"
  if [[ -f "$server_tpl" ]]; then
    _install_substituted "$server_tpl" \
        "${dst}/wakir-spire-server-federation-${side}.container" \
        -e "s/<SIDE>/${side}/g" \
        -e "s/<HOST_BUNDLE_PORT>/8443/g" \
        -e "s/<HOST_GRPC_PORT>/8082/g" \
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
      if ! cmp -s "$server_conf_src" "$server_conf_dst" 2>/dev/null; then
        install -m 644 "$server_conf_src" "$server_conf_dst"
      fi
    else
      log_warn "${server_conf_src} not found in repo; skipping config install"
    fi
    log_ok "SPIRE-server-${side} unit installed (mode=${WAKIR_PILOT_MODE})"
  else
    log_warn "spire-server-federation.container not found at ${server_tpl}"
  fi

  # 6d. SPIRE-Agent-Federation container (per-side substitution).
  #
  # Sprint-9-Tag-5 Bug 7 substance-fix: WAKIR_PILOT_MODE selects which
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
    _install_substituted "$agent_tpl" \
        "${dst}/wakir-spire-agent-${side}.container" \
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
      if ! cmp -s "$agent_conf_src" "$agent_conf_dst" 2>/dev/null; then
        install -m 644 "$agent_conf_src" "$agent_conf_dst"
      fi
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
    if ! cmp -s "${quadlet_src}/wakir-nats.container" "$nats_dst" 2>/dev/null; then
      install -m 644 "${quadlet_src}/wakir-nats.container" "$nats_dst" \
        || { log_err "install wakir-nats.container failed"; return 2; }
    fi
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

  # 6g. Sprint-9-Tag-6 Bug 2 substance-fix: chown the named-volume
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
  # Sprint-9-Tag-8 Bug-21 substance-fix: the previous block swallowed
  # chown stderr via ``2>/dev/null`` and degraded a real failure to a
  # log_warn while still emitting the global ``OK normalised`` line.
  # On Bring-up-4 (AR Fred, 2026-05-14) the volumes stayed root-owned
  # (uid:gid 0:0) even though the bootstrap reported success — chown
  # silently failed and the SPIRE-Agent then crash-looped on first
  # write. Fix: surface chown stderr, hard-verify owner via stat, halt
  # the bootstrap with return-code 2 on mismatch.
  #
  # Sprint-9-Tag-9 Bug-22 substance-fix: on Bring-up-5 (AR Fred,
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
      "wakir-spire-agent-${side}-data" \
      "wakir-spire-agent-${side}-sockets"
  do
    "$WAKIR_BOOTSTRAP_PODMAN" volume create --ignore "$v" >/dev/null 2>&1 || true
    _chown_volume_with_verify "$v" "step-6g-initial" || return 2
  done
  log_ok "named-volume permissions normalised (uid:gid 1000:1000, stat-verified)"

  # 6h. Start the server FIRST. The agent depends on a running server
  # for the join-token attestation handshake; starting them in
  # parallel from a single systemctl-start race-loop reliably loses
  # the first attestation attempt and forces a restart cycle.
  #
  # Sprint-9-Tag-9 Bug-22 substance-fix: defensive re-chown of the
  # server's volume set IMMEDIATELY before systemctl start. Closes
  # the TOC-vs-TOU race window between step 6g's ad-hoc chown and
  # the podman-system-generator's volume reconciliation at service-
  # start. See helper rationale.
  local server_unit="wakir-spire-server-federation-${side}.service"
  if "$WAKIR_BOOTSTRAP_SYSTEMCTL" is-active --quiet "$server_unit"; then
    log_ok "${server_unit} already active"
  else
    _pre_start_chown_sweep "server" "$side" || return 2
    "$WAKIR_BOOTSTRAP_SYSTEMCTL" reset-failed "$server_unit" 2>/dev/null || true
    if ! "$WAKIR_BOOTSTRAP_SYSTEMCTL" start "$server_unit"; then
      log_err "systemctl start ${server_unit} failed"
      log_note "diagnose: journalctl -u ${server_unit} -n 50 --no-pager"
      return 2
    fi
    log_ok "${server_unit} started"
  fi

  # 6i. Sprint-9-Tag-6 Bug 1/15 substance-fix: single-org Phase-1b
  # pilots use the join-token node-attestor. Token generation is a
  # mandatory Operator-Hand step in the Sprint-8 manual recipe; the
  # one-shot bootstrap automates it by issuing
  # ``spire-server token generate`` against the just-started server,
  # parsing the token value, and substituting it into the agent
  # Quadlet's ``Exec=`` line (replacing the literal placeholder
  # ``WAKIR_JOIN_TOKEN_PLACEHOLDER``). Re-run is safe: if the agent
  # is already attested, the token-generate + sed-substitute steps
  # are skipped.
  if [[ "$WAKIR_PILOT_MODE" == "single-org" ]]; then
    local agent_quadlet_dst="${dst}/wakir-spire-agent-${side}.container"
    local agent_already_attested=0
    if "$WAKIR_BOOTSTRAP_PODMAN" exec "wakir-spire-server-federation-${side}" \
         /opt/spire/bin/spire-server agent list 2>/dev/null \
         | grep -q "spiffe://${WAKIR_TRUST_DOMAIN}/${WAKIR_ORG_ID}/agent/pilot"; then
      agent_already_attested=1
      log_ok "agent already attested (skip join-token generate)"
    fi
    if [[ "$agent_already_attested" -eq 0 ]] \
       && [[ -f "$agent_quadlet_dst" ]] \
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
        log_ok "join-token issued for ${jt_spiffe} and injected into agent Quadlet"
        # Daemon-reload so the regenerated Exec= line is picked up
        # before agent start.
        "$WAKIR_BOOTSTRAP_SYSTEMCTL" daemon-reload \
          || { log_err "post-token daemon-reload failed"; return 2; }
      else
        log_err "spire-server token generate produced no parseable token"
        log_note "diagnose: podman exec wakir-spire-server-federation-${side} /opt/spire/bin/spire-server token generate -spiffeID ${jt_spiffe} -ttl 3600"
        return 2
      fi
    elif [[ "$agent_already_attested" -eq 0 ]] \
         && [[ -f "$agent_quadlet_dst" ]]; then
      log_ok "join-token placeholder already substituted (no-op)"
    fi
  fi

  # 6j. Start the agent + NATS. The agent's join-token (if any) is
  # already wired in step 6i; on federation mode the placeholder is
  # left in the Exec= and dropped by a sed-delete handled below.
  if [[ "$WAKIR_PILOT_MODE" == "federation" ]]; then
    local agent_quadlet_dst="${dst}/wakir-spire-agent-${side}.container"
    if [[ -f "$agent_quadlet_dst" ]] \
       && grep -q "WAKIR_JOIN_TOKEN_PLACEHOLDER" "$agent_quadlet_dst"; then
      # Federation agents re-attest via the peer trust-bundle. Strip
      # the literal "-joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER" tail
      # from the Exec= line in place.
      sed -i 's| -joinToken WAKIR_JOIN_TOKEN_PLACEHOLDER||g' \
            "$agent_quadlet_dst" \
        || { log_err "federation-mode token-placeholder sed-delete failed"; return 2; }
      "$WAKIR_BOOTSTRAP_SYSTEMCTL" daemon-reload \
        || { log_err "post-placeholder-strip daemon-reload failed"; return 2; }
      log_ok "federation mode: stripped join-token placeholder from agent Quadlet"
    fi
  fi

  # Sprint-9-Tag-9 Bug-22 substance-fix: defensive re-chown of each
  # container's volume set IMMEDIATELY before its systemctl start.
  # ``server`` is handled in step 6h above; here we handle agent +
  # NATS. The kind-to-volume mapping lives in _pre_start_chown_sweep.
  local unit kind
  for unit in \
      "wakir-spire-agent-${side}.service" \
      "wakir-nats.service"
  do
    if "$WAKIR_BOOTSTRAP_SYSTEMCTL" is-active --quiet "$unit"; then
      log_ok "${unit} already active"
      continue
    fi
    case "$unit" in
      "wakir-spire-agent-${side}.service") kind="agent" ;;
      "wakir-nats.service")                kind="nats"  ;;
      *)                                   kind=""      ;;
    esac
    if [[ -n "$kind" ]]; then
      _pre_start_chown_sweep "$kind" "$side" || return 2
    fi
    "$WAKIR_BOOTSTRAP_SYSTEMCTL" reset-failed "$unit" 2>/dev/null || true
    if ! "$WAKIR_BOOTSTRAP_SYSTEMCTL" start "$unit"; then
      log_err "systemctl start ${unit} failed"
      log_note "diagnose: journalctl -u ${unit} -n 50 --no-pager"
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
  # Sprint-9 Tag-7 substance-fix (Bug-18, Mira-Bug-Bilanz 2026-05-14):
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
