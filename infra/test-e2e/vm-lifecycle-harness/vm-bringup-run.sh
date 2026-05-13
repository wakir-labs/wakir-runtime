#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-9 Tag-5 — Drive wakir-pilot-bootstrap.sh + smoke
#                          against the disposable VM provisioned by
#                          vm-up.sh.
#
# Captures stdout/stderr of the bootstrap into bootstrap-run.log and
# of the smoke check into smoke-run.json. acceptance-gate.sh then
# grades those artefacts.

set -euo pipefail

: "${WAKIR_E2E_STATE_DIR:=/var/lib/wakir-e2e}"
STATE_FILE="$WAKIR_E2E_STATE_DIR/vm.env"

: "${WAKIR_ORG_ID:=acme}"
: "${WAKIR_TRUST_DOMAIN:=wakir.test}"
: "${WAKIR_REPO_BRANCH:=main}"
: "${WAKIR_REPO_URL:=https://github.com/wakir-labs/wakir-runtime.git}"
: "${WAKIR_SKIP_COSIGN_VERIFY:=0}"
: "${WAKIR_SKIP_PROMPTS:=1}"

log()  { echo "[vm-run] $*" >&2; }
die()  { echo "[vm-run] ERROR: $*" >&2; exit 1; }

[[ -f "$STATE_FILE" ]] || die "no state file at $STATE_FILE; run vm-up.sh first"

# shellcheck disable=SC1090
. "$STATE_FILE"

: "${WAKIR_E2E_VM_IP:?VM_IP missing in state file}"
: "${WAKIR_E2E_SSH_KEY:?SSH_KEY missing in state file}"
SSH_PORT="${WAKIR_E2E_SSH_PORT:-22}"

ssh_args=(
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null
  -o ConnectTimeout=15
  -i "$WAKIR_E2E_SSH_KEY"
  -p "$SSH_PORT"
)

# Sanity: disposable marker present?
log "verifying disposable-marker on VM"
if ! ssh "${ssh_args[@]}" "core@$WAKIR_E2E_VM_IP" \
       'test -f /etc/wakir/e2e-disposable-marker'; then
  die "disposable-marker missing on VM; refusing to run against a non-disposable target"
fi

BOOTSTRAP_LOG="$WAKIR_E2E_STATE_DIR/bootstrap-run.log"
SMOKE_JSON="$WAKIR_E2E_STATE_DIR/smoke-run.json"
SMOKE_LOG="$WAKIR_E2E_STATE_DIR/smoke-run.log"

log "running wakir-pilot-bootstrap.sh inside VM"
set +e
# We pipe the bootstrap from raw.githubusercontent.com -- this is the
# canonical Operator-Hand invocation form (see PROXMOX_BRING_UP_RECIPE.md
# §"Aufruf"). The remote URL is pinned by WAKIR_REPO_BRANCH.
ssh "${ssh_args[@]}" "core@$WAKIR_E2E_VM_IP" bash -se <<EOSSH >"$BOOTSTRAP_LOG" 2>&1
set -u
export WAKIR_ORG_ID="$WAKIR_ORG_ID"
export WAKIR_TRUST_DOMAIN="$WAKIR_TRUST_DOMAIN"
export WAKIR_REPO_BRANCH="$WAKIR_REPO_BRANCH"
export WAKIR_REPO_URL="$WAKIR_REPO_URL"
export WAKIR_SKIP_COSIGN_VERIFY="$WAKIR_SKIP_COSIGN_VERIFY"
export WAKIR_SKIP_PROMPTS="$WAKIR_SKIP_PROMPTS"

# Canonical curl-piped invocation:
curl -sSL "https://raw.githubusercontent.com/wakir-labs/wakir-runtime/${WAKIR_REPO_BRANCH}/infra/spire/federation/wakir-pilot-bootstrap.sh" | sudo -E bash
EOSSH
BOOTSTRAP_RC=$?
set -e
log "bootstrap exit: $BOOTSTRAP_RC (log: $BOOTSTRAP_LOG)"

log "running proxmox-bringup-smoke --org $WAKIR_ORG_ID --json"
set +e
ssh "${ssh_args[@]}" "core@$WAKIR_E2E_VM_IP" \
    "sudo /opt/wakir-runtime/bin/proxmox-bringup-smoke --org $WAKIR_ORG_ID --json" \
    > "$SMOKE_JSON" 2>"$SMOKE_LOG"
SMOKE_RC=$?
set -e
log "smoke exit: $SMOKE_RC (json: $SMOKE_JSON, log: $SMOKE_LOG)"

# Persist exit codes for the gate
cat > "$WAKIR_E2E_STATE_DIR/run.env" <<EOF
WAKIR_E2E_BOOTSTRAP_RC=$BOOTSTRAP_RC
WAKIR_E2E_SMOKE_RC=$SMOKE_RC
WAKIR_E2E_BOOTSTRAP_LOG=$BOOTSTRAP_LOG
WAKIR_E2E_SMOKE_JSON=$SMOKE_JSON
WAKIR_E2E_SMOKE_LOG=$SMOKE_LOG
EOF

log "run complete; artefacts under $WAKIR_E2E_STATE_DIR"
