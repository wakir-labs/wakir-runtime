#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-Tag-8 — Live-VM-Acceptance CI-Wrapper
# (Sprint-7 Item: codify the operator-hand procedure into a CI-callable
#  wrapper script).
#
# **Why this script exists.**
#
# `scripts/federation-live-vm-acceptance.sh` is the source-of-truth
# acceptance lane (Tomás Tag-6/9 substrate). It runs ON the Pilot-VM,
# as root, after the substrate has been installed at
# /opt/wakir-runtime. That covers the manual Operator-Hand path.
#
# This wrapper adds the **CI-callable** half: an SSH-driven script
# that runs on the operator host (or a CI runner with SSH credentials
# to the target VM), pulls the repo into the right place, resets
# federation-config from source, invokes the on-VM acceptance script,
# and emits a summary-JSON to stdout for CI ingestion.
#
# Sandbox boundary
# ----------------
#
# This wrapper DOES NOT run in the claude-dev Sandbox. The Sandbox
# cannot reach 192.168.178.* — see feedback_sandbox_host_trennung.md.
# It runs on an operator-controlled host (Mira-Hand) or a CI runner
# that has SSH access to wakir-orbit / wakir-pilot.
#
# Invocation
# ----------
#
#   ./scripts/ci-live-vm-acceptance-wrapper.sh \
#       --target wakir-orbit \
#       --ssh-user operator \
#       --ssh-key  ~/.ssh/wakir-orbit \
#       --side     orbit \
#       --peer-side wakir \
#       --peer-host 192.168.178.116 \
#       --federation-mode auto
#
# Required flags:
#   --target          SSH host (DNS name or IP). The wrapper does NOT
#                     hard-code 192.168.178.* — the operator passes
#                     the target explicitly so the same wrapper works
#                     for wakir-pilot AND wakir-orbit AND any future
#                     Phase-3 production host.
#   --ssh-user        SSH login on the target. The wrapper assumes
#                     sudo-NOPASSWD on the target for this user (the
#                     acceptance script needs root).
#   --ssh-key         Private-key path. The wrapper does NOT touch
#                     ssh-agent; the key path is explicit so the CI
#                     runner can manage its own key lifecycle.
#
# Optional flags:
#   --side                  Same semantics as WAKIR_SIDE on the target.
#                           Default: orbit.
#   --peer-side             WAKIR_PEER_SIDE on the target. Default: wakir.
#   --peer-host             WAKIR_PEER_HOST on the target. Default: 192.168.178.116
#                           (matches the dogfood-LAN topology).
#   --federation-mode       single-org | federation | auto.
#                           ``auto`` detects from the substrate state:
#                           if the target already has a
#                           wakir-spire-server-federation-*.service
#                           loaded, federation-mode is selected;
#                           else single-org-mode. Default: auto.
#   --repo-url              Repo to pull into /opt/wakir-runtime on
#                           the target. Default:
#                           https://github.com/wakir-labs/wakir-runtime.git
#   --repo-branch           Default: main.
#   --skip-cosign-verify    Pass through to the bootstrap. Default: 1
#                           (parity with the on-VM acceptance script).
#   --summary-json          Output path for the summary-JSON; default
#                           is stdout. CI passes a file path so the
#                           summary lands on the runner FS.
#   --pre-check-only        Run the SSH + repo-pull precheck but do
#                           NOT invoke the acceptance script on the
#                           target. Useful for dry-run + connection
#                           verification.
#   --help, -h              Show this help and exit.
#
# Exit codes
# ----------
#
#   0  Acceptance PASS — on-VM script returned 0.
#   1  Pre-check failed (SSH connection, repo-pull, ...) — substrate
#      problem on the target or operator-host.
#   2  Acceptance FAIL — on-VM script returned non-zero.
#   3  Wrapper-internal error (bad argv, missing tool, ...).
#
# Summary-JSON shape
# ------------------
#
#   {
#     "target":           "wakir-orbit",
#     "side":             "orbit",
#     "peer_side":        "wakir",
#     "peer_host":        "192.168.178.116",
#     "federation_mode":  "federation",
#     "started_utc":      "2026-05-16T01:00:00Z",
#     "finished_utc":     "2026-05-16T01:05:42Z",
#     "ssh_precheck":     "ok",
#     "repo_pull":        "ok",
#     "federation_config_reset": "ok",
#     "acceptance_rc":    0,
#     "acceptance_summary": "Federation Live-VM Acceptance: PASS",
#     "bug_regressions": ["Bug-30", "Bug-31", "Bug-32", "Bug-33",
#                         "Bug-36", "Bug-37", "Bug-38"]
#   }
#
# -- Kai

set -eu -o pipefail

PROG=$(basename "$0")

# ---------------------------------------------------------------------------
# Defaults + argparse.
# ---------------------------------------------------------------------------

TARGET=""
SSH_USER=""
SSH_KEY=""
SIDE="orbit"
PEER_SIDE="wakir"
PEER_HOST="192.168.178.116"
FEDERATION_MODE="auto"
REPO_URL="https://github.com/wakir-labs/wakir-runtime.git"
REPO_BRANCH="main"
SKIP_COSIGN_VERIFY="1"
SUMMARY_JSON=""
PRE_CHECK_ONLY=0

usage() {
  sed -n '2,90p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)               TARGET="${2:-}";               shift 2;;
    --ssh-user)             SSH_USER="${2:-}";             shift 2;;
    --ssh-key)              SSH_KEY="${2:-}";              shift 2;;
    --side)                 SIDE="${2:-}";                 shift 2;;
    --peer-side)            PEER_SIDE="${2:-}";            shift 2;;
    --peer-host)            PEER_HOST="${2:-}";            shift 2;;
    --federation-mode)      FEDERATION_MODE="${2:-}";      shift 2;;
    --repo-url)             REPO_URL="${2:-}";             shift 2;;
    --repo-branch)          REPO_BRANCH="${2:-}";          shift 2;;
    --skip-cosign-verify)   SKIP_COSIGN_VERIFY="${2:-}";   shift 2;;
    --summary-json)         SUMMARY_JSON="${2:-}";         shift 2;;
    --pre-check-only)       PRE_CHECK_ONLY=1;              shift;;
    -h|--help)              usage; exit 0;;
    *)
      echo "[$PROG] ERROR: unknown argument: $1" >&2
      usage >&2
      exit 3
      ;;
  esac
done

# Required-flag validation.
missing=()
[[ -z "$TARGET"   ]] && missing+=("--target")
[[ -z "$SSH_USER" ]] && missing+=("--ssh-user")
[[ -z "$SSH_KEY"  ]] && missing+=("--ssh-key")
if [[ "${#missing[@]}" -gt 0 ]]; then
  echo "[$PROG] ERROR: missing required flags: ${missing[*]}" >&2
  usage >&2
  exit 3
fi

# Federation-mode argument validation.
case "$FEDERATION_MODE" in
  single-org|federation|auto) : ;;
  *)
    echo "[$PROG] ERROR: --federation-mode must be single-org|federation|auto; got '$FEDERATION_MODE'" >&2
    exit 3
    ;;
esac

# Tool-precheck on the operator-host.
for tool in ssh scp jq; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "[$PROG] ERROR: required tool '$tool' not in PATH on operator-host" >&2
    exit 3
  fi
done
if [[ ! -r "$SSH_KEY" ]]; then
  echo "[$PROG] ERROR: ssh-key not readable: $SSH_KEY" >&2
  exit 3
fi

# Timestamp helpers.
utc_now() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# Build summary-JSON skeleton; we mutate it in-place as we go.
declare -A summary=(
  [target]="$TARGET"
  [side]="$SIDE"
  [peer_side]="$PEER_SIDE"
  [peer_host]="$PEER_HOST"
  [federation_mode]="$FEDERATION_MODE"
  [started_utc]="$(utc_now)"
  [finished_utc]=""
  [ssh_precheck]="pending"
  [repo_pull]="pending"
  [federation_config_reset]="pending"
  [acceptance_rc]="0"
  [acceptance_summary]=""
)

log()  { printf '[%s] %s\n' "$PROG" "$*" >&2; }
warn() { printf '[%s] WARN: %s\n' "$PROG" "$*" >&2; }

emit_summary() {
  summary[finished_utc]="$(utc_now)"
  # Build the JSON via jq for proper string-escaping.
  local json
  json=$(jq -n \
    --arg target               "${summary[target]}" \
    --arg side                 "${summary[side]}" \
    --arg peer_side            "${summary[peer_side]}" \
    --arg peer_host            "${summary[peer_host]}" \
    --arg federation_mode      "${summary[federation_mode]}" \
    --arg started_utc          "${summary[started_utc]}" \
    --arg finished_utc         "${summary[finished_utc]}" \
    --arg ssh_precheck         "${summary[ssh_precheck]}" \
    --arg repo_pull            "${summary[repo_pull]}" \
    --arg federation_config_reset "${summary[federation_config_reset]}" \
    --argjson acceptance_rc    "${summary[acceptance_rc]}" \
    --arg acceptance_summary   "${summary[acceptance_summary]}" \
    '{
       target: $target,
       side: $side,
       peer_side: $peer_side,
       peer_host: $peer_host,
       federation_mode: $federation_mode,
       started_utc: $started_utc,
       finished_utc: $finished_utc,
       ssh_precheck: $ssh_precheck,
       repo_pull: $repo_pull,
       federation_config_reset: $federation_config_reset,
       acceptance_rc: $acceptance_rc,
       acceptance_summary: $acceptance_summary,
       bug_regressions: [
         "Bug-30","Bug-31","Bug-32","Bug-33",
         "Bug-36","Bug-37","Bug-38"
       ]
     }')
  if [[ -n "$SUMMARY_JSON" ]]; then
    printf '%s\n' "$json" > "$SUMMARY_JSON"
    log "summary-json written to: $SUMMARY_JSON"
  else
    printf '%s\n' "$json"
  fi
}

ssh_target() {
  ssh -i "$SSH_KEY" \
      -o BatchMode=yes \
      -o StrictHostKeyChecking=accept-new \
      -o ConnectTimeout=10 \
      "$SSH_USER@$TARGET" \
      "$@"
}

# ---------------------------------------------------------------------------
# Phase 1: SSH precheck + connection verification.
# ---------------------------------------------------------------------------

log "phase 1: SSH precheck against $SSH_USER@$TARGET"
if ! ssh_target true 2>/dev/null; then
  summary[ssh_precheck]="fail"
  log "SSH precheck FAILED — cannot connect to $SSH_USER@$TARGET with key $SSH_KEY"
  emit_summary
  exit 1
fi
summary[ssh_precheck]="ok"
log "phase 1: SSH precheck OK"

# Sudo-NOPASSWD check — the acceptance script needs root.
if ! ssh_target "sudo -n true" 2>/dev/null; then
  summary[ssh_precheck]="ok-but-no-sudo-nopasswd"
  log "SSH OK but sudo-NOPASSWD not configured; acceptance will prompt"
  warn "consider configuring 'wakir-acceptance ALL=(ALL) NOPASSWD: ALL' for $SSH_USER on $TARGET"
fi

# ---------------------------------------------------------------------------
# Phase 2: repo-pull /opt/wakir-runtime on the target.
# ---------------------------------------------------------------------------

log "phase 2: repo-pull /opt/wakir-runtime on $TARGET (branch=$REPO_BRANCH)"

# The pull script runs ON the target. We pass it inline via SSH so the
# operator-host does not have to scp it. The script is idempotent:
# clone-if-missing, fetch+reset-if-present.
pull_script=$(cat <<'EOF'
set -eu -o pipefail
REPO_URL="$1"
REPO_BRANCH="$2"
ROOT="/opt/wakir-runtime"
if [[ ! -d "$ROOT/.git" ]]; then
  sudo git clone --branch "$REPO_BRANCH" --depth 50 "$REPO_URL" "$ROOT"
else
  sudo git -C "$ROOT" fetch --depth 50 origin "$REPO_BRANCH"
  sudo git -C "$ROOT" reset --hard "origin/$REPO_BRANCH"
fi
sudo git -C "$ROOT" rev-parse HEAD
EOF
)

set +e
target_head=$(ssh_target "bash -s -- '$REPO_URL' '$REPO_BRANCH'" <<<"$pull_script" 2>&1)
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  summary[repo_pull]="fail"
  log "repo-pull FAILED on $TARGET:"
  printf '%s\n' "$target_head" >&2
  emit_summary
  exit 1
fi
summary[repo_pull]="ok"
# target_head's last line is the HEAD sha; capture it.
target_head_sha=$(printf '%s\n' "$target_head" | tail -n1)
log "phase 2: repo-pull OK; HEAD=$target_head_sha"

# ---------------------------------------------------------------------------
# Phase 3: federation-config reset from source.
# ---------------------------------------------------------------------------
#
# The acceptance lane assumes the federation-config files on the
# target match the wakir-runtime source byte-for-byte. The repo-pull
# above already reset everything under /opt/wakir-runtime, but the
# bootstrap-step-6 installed copies at /etc/spire-* and
# /etc/containers/systemd/ may have drifted from prior Operator-Hand
# patches. We force a clean re-install on the next acceptance-script
# run by removing the installed copies; the bootstrap then re-installs
# them from /opt/wakir-runtime/infra/spire/federation/config/ at
# step-6.

log "phase 3: federation-config reset (drops installed /etc/spire-* + /etc/containers/systemd/wakir-* + restarts daemon)"
reset_script=$(cat <<'EOF'
set -eu -o pipefail
sudo rm -f /etc/spire-server-*.conf /etc/spire-agent-*.conf 2>/dev/null || true
# Drop ONLY the wakir-* Quadlets the bootstrap re-installs at step-6;
# do NOT touch other systemd units.
sudo find /etc/containers/systemd/ -maxdepth 1 -name 'wakir-spire-*.container' -delete 2>/dev/null || true
sudo find /etc/containers/systemd/ -maxdepth 1 -name 'wakir-spire-*.volume'    -delete 2>/dev/null || true
sudo find /etc/containers/systemd/ -maxdepth 1 -name 'wakir-federation*'       -delete 2>/dev/null || true
# Reload systemd so the Quadlet generator picks up the deletions.
sudo systemctl daemon-reload
EOF
)

set +e
reset_out=$(ssh_target "bash -s" <<<"$reset_script" 2>&1)
rc=$?
set -e
if [[ $rc -ne 0 ]]; then
  summary[federation_config_reset]="fail"
  log "federation-config reset FAILED on $TARGET:"
  printf '%s\n' "$reset_out" >&2
  emit_summary
  exit 1
fi
summary[federation_config_reset]="ok"
log "phase 3: federation-config reset OK"

# ---------------------------------------------------------------------------
# Pre-check-only short-circuit.
# ---------------------------------------------------------------------------

if [[ "$PRE_CHECK_ONLY" -eq 1 ]]; then
  log "--pre-check-only set; skipping phase 4 (acceptance-script invocation)"
  summary[acceptance_summary]="pre-check-only; acceptance not run"
  emit_summary
  exit 0
fi

# ---------------------------------------------------------------------------
# Phase 4: invoke the acceptance-script on the target.
# ---------------------------------------------------------------------------

# Federation-mode auto-detect: ask the target which mode it is in. The
# bootstrap-step-6 leaves a marker file at
# /etc/wakir/pilot-mode that records the WAKIR_PILOT_MODE used on the
# last bring-up. If the marker is missing (very first bring-up), we
# fall back to inspecting which Quadlet unit is loaded.
if [[ "$FEDERATION_MODE" == "auto" ]]; then
  log "phase 4 pre-step: auto-detect federation-mode on $TARGET"
  detect_script=$(cat <<'EOF'
set -eu -o pipefail
if [[ -r /etc/wakir/pilot-mode ]]; then
  cat /etc/wakir/pilot-mode
elif systemctl list-unit-files 'wakir-spire-server-federation-*.service' 2>/dev/null | grep -q .; then
  echo "federation"
else
  echo "single-org"
fi
EOF
)
  set +e
  detected_mode=$(ssh_target "bash -s" <<<"$detect_script" 2>&1 | tail -n1)
  set -e
  case "$detected_mode" in
    single-org|federation)
      FEDERATION_MODE="$detected_mode"
      summary[federation_mode]="$detected_mode"
      log "phase 4 pre-step: auto-detected federation-mode=$detected_mode"
      ;;
    *)
      warn "auto-detect returned unexpected '$detected_mode'; defaulting to federation"
      FEDERATION_MODE="federation"
      summary[federation_mode]="federation"
      ;;
  esac
fi

log "phase 4: invoking on-VM federation-live-vm-acceptance.sh (mode=$FEDERATION_MODE)"

# We pass through the standard env-vars the on-VM acceptance script
# consumes. WAKIR_PILOT_MODE is what the bootstrap inside the acceptance
# script uses.
accept_cmd="sudo WAKIR_SIDE='$SIDE' \
  WAKIR_PEER_SIDE='$PEER_SIDE' \
  WAKIR_PEER_HOST='$PEER_HOST' \
  WAKIR_PILOT_MODE='$FEDERATION_MODE' \
  WAKIR_SKIP_COSIGN_VERIFY='$SKIP_COSIGN_VERIFY' \
  bash /opt/wakir-runtime/scripts/federation-live-vm-acceptance.sh"

set +e
accept_out=$(ssh_target "$accept_cmd" 2>&1)
rc=$?
set -e
summary[acceptance_rc]="$rc"

# Extract a one-line summary from the last "Federation Live-VM
# Acceptance:" log-line if present.
accept_summary_line=$(printf '%s\n' "$accept_out" | grep -E 'Federation Live-VM Acceptance: (PASS|FAIL)' | tail -n1 || true)
if [[ -z "$accept_summary_line" ]]; then
  # No summary line found; capture the last 3 lines as a fallback.
  accept_summary_line=$(printf '%s\n' "$accept_out" | tail -n3 | tr '\n' ' ')
fi
summary[acceptance_summary]="$accept_summary_line"

if [[ $rc -ne 0 ]]; then
  log "acceptance FAILED on $TARGET (rc=$rc); last 30 lines of output:"
  printf '%s\n' "$accept_out" | tail -n30 >&2
  emit_summary
  exit 2
fi

log "phase 4: acceptance PASS"
emit_summary
exit 0
