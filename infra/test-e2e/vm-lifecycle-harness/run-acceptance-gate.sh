#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-9 Tag-5 — One-shot Acceptance-Gate orchestrator.
#
# Runs vm-up.sh + vm-bringup-run.sh + acceptance-gate.sh in order and
# unconditionally tears down via trap EXIT (success or failure). This
# is the canonical Operator-Hand invocation; for debugging the
# individual scripts may also be invoked separately.
#
# Sandbox-Grenze (ADR-0051): MUST NOT run in claude-dev.

set -u

# Resolve own dir before set -e (path resolution should not abort early).
HERE="$(dirname "$(readlink -f "$0")")"
set -e

ORG=acme
BRANCH=main
PROVIDER=qemu
NO_TEARDOWN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --org)            ORG="$2"; shift 2 ;;
    --branch)         BRANCH="$2"; shift 2 ;;
    --provider)       PROVIDER="$2"; shift 2 ;;
    --no-teardown)    NO_TEARDOWN=1; shift ;;
    -h|--help)
      cat <<EOF
Usage: $0 [--org <id>] [--branch <git-branch>] [--provider <qemu|proxmox>] [--no-teardown]

Runs the disposable-VM acceptance gate end-to-end. Default: ORG=acme,
BRANCH=main, PROVIDER=qemu, teardown enabled.

Exit codes:
  0  Acceptance-Gate PASS
  2  Acceptance-Gate FAIL (with bug-vector classification)
  3  Required artefacts missing
  4  vm-up.sh failed
  5  vm-bringup-run.sh failed
EOF
      exit 0
      ;;
    *) echo "unknown flag: $1" >&2; exit 1 ;;
  esac
done

export WAKIR_ORG_ID="$ORG"
export WAKIR_REPO_BRANCH="$BRANCH"
export WAKIR_E2E_VM_PROVIDER="$PROVIDER"

teardown() {
  rc=$?
  if [[ "$NO_TEARDOWN" == "1" ]]; then
    echo "[orchestrator] --no-teardown set; leaving VM intact (state: $WAKIR_E2E_STATE_DIR/vm.env)" >&2
  else
    echo "[orchestrator] running vm-down.sh (trap EXIT)" >&2
    bash "$HERE/vm-down.sh" || true
  fi
  exit "$rc"
}

: "${WAKIR_E2E_STATE_DIR:=/var/lib/wakir-e2e}"
export WAKIR_E2E_STATE_DIR
mkdir -p "$WAKIR_E2E_STATE_DIR"

trap teardown EXIT

echo "[orchestrator] step 1/3: vm-up.sh"
bash "$HERE/vm-up.sh" || { echo "[orchestrator] vm-up failed"; exit 4; }

echo "[orchestrator] step 2/3: vm-bringup-run.sh"
bash "$HERE/vm-bringup-run.sh" || { echo "[orchestrator] vm-bringup-run failed"; exit 5; }

echo "[orchestrator] step 3/3: acceptance-gate.sh"
bash "$HERE/acceptance-gate.sh"
gate_rc=$?
echo "[orchestrator] gate exit: $gate_rc"
exit "$gate_rc"
