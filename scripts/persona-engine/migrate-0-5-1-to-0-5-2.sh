#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Licensed under the Business Source License 1.1; see
# wirelang/persona_engine/LICENSE-BSL.md.
# Change Date: 2030-05-15. Change License: Apache License 2.0.
#
# Persona-Engine Migration Helper — Operator-Hand entry script
# ============================================================
#
# Tag-53 (2026-05-19). Wraps the Python helpers in
# `scripts/persona-engine/migrate_0_5_1_to_0_5_2_helpers.py` with an
# operator-facing Bash CLI for the KW-24 Live-VM rotation of the
# Wakir persona-engine image from `0.5.1-pre-cutover`
# (Tag-48 PR #313) to `0.5.2-final-pre-cutover` (Tag-52 PR #336).
#
# Sandbox boundary
# ----------------
#
# This script is OPERATOR-HAND. It runs on the Live-VM, as root,
# under Operator-Hand control. It is NOT run in the claude-dev
# sandbox. The hermetic Tag-53 test suite in
# `wirelang/tests/persona_engine/test_migrate_0_5_1_to_0_5_2_tag53.py`
# exercises the Python helpers directly without invoking this Bash
# wrapper, so the test suite remains hermetic even though the
# wrapper is operator-only.
#
# Why a Bash wrapper at all?
# --------------------------
#
# The Operator-Hand surface for KW-24 cutover is bash/systemd. A
# python3 entrypoint would require the operator to know the import
# layout of the wakir-runtime tree; a Bash wrapper keeps the
# invocation flat. The wrapper delegates all logic to the Python
# helper module (single source of truth); it only handles:
#
#   1. CLI flag parsing.
#   2. Sub-command dispatch (pre-check / rotation-plan / rotate /
#      post-verify / rollback / full).
#   3. Exit-code translation (0/1/2 conventions for Operator-Hand
#      automation).
#   4. The actual rotation `--apply` mode (snapshot + sed + reload
#      + restart). The pre-check and post-verify modes are
#      read-only; the `--apply` mode is the one that mutates the
#      Live-VM.
#
# Invocation
# ----------
#
#   ./migrate-0-5-1-to-0-5-2.sh pre-check \
#       [--repo-root /opt/wakir-runtime]
#
#   ./migrate-0-5-1-to-0-5-2.sh rotation-plan \
#       [--repo-root /opt/wakir-runtime] \
#       [--quadlet-path /etc/containers/systemd/wakir-persona-engine.container]
#
#   ./migrate-0-5-1-to-0-5-2.sh rotate --apply \
#       [--repo-root /opt/wakir-runtime] \
#       [--quadlet-path /etc/containers/systemd/wakir-persona-engine.container]
#
#   ./migrate-0-5-1-to-0-5-2.sh post-verify \
#       --image-tag 0.5.2-final-pre-cutover \
#       --manifest-version 0.5.2-final-pre-cutover \
#       --boot-record-count 10
#
#   ./migrate-0-5-1-to-0-5-2.sh rollback-plan \
#       [--repo-root /opt/wakir-runtime] \
#       [--quadlet-path /etc/containers/systemd/wakir-persona-engine.container]
#
#   ./migrate-0-5-1-to-0-5-2.sh rollback --apply \
#       [--repo-root /opt/wakir-runtime] \
#       [--quadlet-path /etc/containers/systemd/wakir-persona-engine.container]
#
# Exit codes
# ----------
#
#   0  success / advisory output (read-only modes)
#   1  CLI usage error (bad flags, missing sub-command)
#   2  check failed — see structured output for the failed step
#   3  apply-mode failure — partial rotation; see rollback-plan
#
# ADR anchors
# -----------
#
# - ADR-0036 (self-migration converter)
# - ADR-0043 (persona-engine engineer mandate)
# - ADR-0065 / ADR-0066 (cutover discipline)
#
# Cross-zone discipline
# ---------------------
#
# This script touches the Quadlet file (Kai-domain, Zone-J advisory)
# only in `--apply` mode and only for the Image= line tag string.
# It does NOT touch:
#
#   - WAT-core / OTS-anchor logic (Tomás, Zone-K).
#   - Identity-substrate keys (Reza, Zone-L).
#   - Persona-definition files (Aisha).
#
# Operators are expected to run this script under Kai's runbook
# guidance; the script writes a snapshot of the Quadlet file
# before any sed-edit so Kai can audit the diff post-rotation.

set -euo pipefail

# ---------------------------------------------------------------------------
# Logging helpers (stable prefix for journalctl correlation)
# ---------------------------------------------------------------------------

LOG_PREFIX="persona-engine-migrate-0-5-1-to-0-5-2"

# Log lines go to STDERR so STDOUT remains a pure JSON channel for the
# read-only sub-commands (pre-check / rotation-plan / rollback-plan /
# post-verify). Operator-Hand redirection captures journalctl-style
# logs on 2> and JSON on 1>.
log()  { printf '[%s] [%s] %s\n' "$(date -u +%FT%TZ)" "$LOG_PREFIX" "$*" >&2; }
err()  { printf '[%s] [%s] [ERROR] %s\n' "$(date -u +%FT%TZ)" "$LOG_PREFIX" "$*" >&2; }
fail() { err "$1"; exit "${2:-2}"; }

# ---------------------------------------------------------------------------
# CLI parsing
# ---------------------------------------------------------------------------

usage() {
  cat <<'EOF'
Usage: migrate-0-5-1-to-0-5-2.sh <subcommand> [options]

Subcommands:
  pre-check           Read-only hash-check of in-tree manifest + pin-pack.
  rotation-plan       Emit the operator-applicable rotation plan (JSON).
  rotate --apply      Execute the rotation (mutates Live-VM Quadlet).
  post-verify         Verify a post-rotation observation snapshot.
  rollback-plan       Emit the rollback plan (JSON).
  rollback --apply    Execute the rollback (mutates Live-VM Quadlet).

Common options:
  --repo-root PATH       Path to wakir-runtime repo (default: auto-detect).
  --quadlet-path PATH    Persona-engine Quadlet file on this VM
                         (default: /etc/containers/systemd/wakir-persona-engine.container).

post-verify options:
  --image-tag TAG               Observed image tag (string).
  --manifest-version VER        Observed manifest_version label (string).
  --boot-record-count N         Observed BackendDecision record count (int).

Exit codes: 0=ok, 1=usage, 2=check-failed, 3=apply-failed.
EOF
}

if [[ $# -lt 1 ]]; then
  usage >&2
  exit 1
fi

SUBCOMMAND="$1"
shift

REPO_ROOT=""
QUADLET_PATH="/etc/containers/systemd/wakir-persona-engine.container"
APPLY=0
PV_IMAGE_TAG=""
PV_MANIFEST_VERSION=""
PV_BOOT_RECORD_COUNT=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo-root)        REPO_ROOT="$2"; shift 2;;
    --quadlet-path)     QUADLET_PATH="$2"; shift 2;;
    --apply)            APPLY=1; shift;;
    --image-tag)        PV_IMAGE_TAG="$2"; shift 2;;
    --manifest-version) PV_MANIFEST_VERSION="$2"; shift 2;;
    --boot-record-count) PV_BOOT_RECORD_COUNT="$2"; shift 2;;
    -h|--help)          usage; exit 0;;
    *)                  err "unknown option: $1"; usage >&2; exit 1;;
  esac
done

# ---------------------------------------------------------------------------
# Repo-root + python helper resolution
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
HELPER_PY="${SCRIPT_DIR}/migrate_0_5_1_to_0_5_2_helpers.py"

if [[ ! -f "$HELPER_PY" ]]; then
  fail "helper module not found at $HELPER_PY" 1
fi

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
  fail "python3 not found on PATH (override via PYTHON= env)" 1
fi

# Build common helper-arg array.
declare -a HELPER_COMMON=()
if [[ -n "$REPO_ROOT" ]]; then
  HELPER_COMMON+=(--repo-root "$REPO_ROOT")
fi
HELPER_COMMON+=(--quadlet-path "$QUADLET_PATH")

# ---------------------------------------------------------------------------
# Sub-command dispatch
# ---------------------------------------------------------------------------

case "$SUBCOMMAND" in

  pre-check)
    log "running pre-rotation hash check"
    set +e
    "$PY" "$HELPER_PY" "${HELPER_COMMON[@]}" pre-check
    rc=$?
    set -e
    if [[ $rc -ne 0 ]]; then
      err "pre-check failed (exit=$rc); see JSON above for failing steps"
      exit "$rc"
    fi
    log "pre-check OK"
    ;;

  rotation-plan)
    log "emitting rotation plan"
    "$PY" "$HELPER_PY" "${HELPER_COMMON[@]}" rotation-plan
    ;;

  rotate)
    if [[ $APPLY -ne 1 ]]; then
      err "'rotate' requires --apply to mutate the Live-VM"
      err "(use 'rotation-plan' for the read-only plan)"
      exit 1
    fi
    log "running pre-check before apply"
    PRECHECK_OUT="$(mktemp -t persona-engine-pre-check.XXXXXX.json)"
    set +e
    "$PY" "$HELPER_PY" "${HELPER_COMMON[@]}" pre-check >"$PRECHECK_OUT"
    rc=$?
    set -e
    if [[ $rc -ne 0 ]]; then
      cat "$PRECHECK_OUT"
      rm -f "$PRECHECK_OUT"
      fail "pre-check failed; aborting rotate (no Live-VM mutation)" 2
    fi
    rm -f "$PRECHECK_OUT"
    log "pre-check OK; commencing rotation"

    if [[ ! -f "$QUADLET_PATH" ]]; then
      fail "Quadlet not found at $QUADLET_PATH; rotation aborted" 3
    fi

    SNAPSHOT="${QUADLET_PATH}.pre-0-5-2-final"
    if [[ -f "$SNAPSHOT" ]]; then
      log "WARN: snapshot $SNAPSHOT already exists; keeping as-is"
    else
      log "snapshotting Quadlet to $SNAPSHOT"
      cp -p "$QUADLET_PATH" "$SNAPSHOT"
    fi

    log "editing Image= line: 0.5.1-pre-cutover -> 0.5.2-final-pre-cutover"
    sed -i \
      's|wakir-persona-engine:0.5.1-pre-cutover|wakir-persona-engine:0.5.2-final-pre-cutover|g' \
      "$QUADLET_PATH" || fail "sed edit failed" 3

    if command -v podman >/dev/null 2>&1; then
      log "validating Quadlet via podman quadlet-validate"
      if ! podman quadlet-validate "$QUADLET_PATH"; then
        log "quadlet-validate failed; restoring snapshot"
        mv "$SNAPSHOT" "$QUADLET_PATH"
        fail "quadlet-validate failed; rolled back via snapshot" 3
      fi
    else
      log "WARN: podman not on PATH; skipping quadlet-validate"
    fi

    log "systemctl daemon-reload"
    if ! systemctl daemon-reload; then
      log "daemon-reload failed; restoring snapshot"
      mv "$SNAPSHOT" "$QUADLET_PATH"
      systemctl daemon-reload || true
      fail "daemon-reload failed; rolled back via snapshot" 3
    fi

    log "systemctl restart wakir-persona-engine.service"
    if ! systemctl restart wakir-persona-engine.service; then
      log "restart failed; restoring snapshot + re-restarting"
      mv "$SNAPSHOT" "$QUADLET_PATH"
      systemctl daemon-reload || true
      systemctl restart wakir-persona-engine.service || true
      fail "restart failed; rolled back via snapshot" 3
    fi

    log "rotation complete; capture post-verify snapshot via:"
    log "  journalctl -u wakir-persona-engine.service --since='-2min' | grep backend-decision | head -n 12"
    log "then run: $0 post-verify --image-tag 0.5.2-final-pre-cutover ..."
    ;;

  post-verify)
    if [[ -z "$PV_IMAGE_TAG" || -z "$PV_MANIFEST_VERSION" || -z "$PV_BOOT_RECORD_COUNT" ]]; then
      err "post-verify requires --image-tag --manifest-version --boot-record-count"
      exit 1
    fi
    log "verifying post-rotation snapshot"
    set +e
    "$PY" "$HELPER_PY" "${HELPER_COMMON[@]}" post-verify \
      --image-tag "$PV_IMAGE_TAG" \
      --manifest-version "$PV_MANIFEST_VERSION" \
      --boot-record-count "$PV_BOOT_RECORD_COUNT"
    rc=$?
    set -e
    if [[ $rc -ne 0 ]]; then
      err "post-verify failed (exit=$rc); see JSON above for failing steps"
      exit "$rc"
    fi
    log "post-verify OK"
    ;;

  rollback-plan)
    log "emitting rollback plan"
    "$PY" "$HELPER_PY" "${HELPER_COMMON[@]}" rollback-plan
    ;;

  rollback)
    if [[ $APPLY -ne 1 ]]; then
      err "'rollback' requires --apply to mutate the Live-VM"
      err "(use 'rollback-plan' for the read-only plan)"
      exit 1
    fi
    if [[ ! -f "$QUADLET_PATH" ]]; then
      fail "Quadlet not found at $QUADLET_PATH; rollback aborted" 3
    fi
    SNAPSHOT="${QUADLET_PATH}.pre-0-5-2-final"
    if [[ -f "$SNAPSHOT" ]]; then
      log "restoring snapshot from $SNAPSHOT"
      mv "$SNAPSHOT" "$QUADLET_PATH"
    else
      log "snapshot absent; falling back to inverse sed-edit"
      sed -i \
        's|wakir-persona-engine:0.5.2-final-pre-cutover|wakir-persona-engine:0.5.1-pre-cutover|g' \
        "$QUADLET_PATH" || fail "sed undo failed" 3
    fi
    if command -v podman >/dev/null 2>&1; then
      log "validating rolled-back Quadlet"
      podman quadlet-validate "$QUADLET_PATH" || \
        fail "rolled-back Quadlet failed quadlet-validate" 3
    fi
    log "systemctl daemon-reload (rollback)"
    systemctl daemon-reload || fail "daemon-reload failed (rollback)" 3
    log "systemctl restart wakir-persona-engine.service (rollback)"
    systemctl restart wakir-persona-engine.service || \
      fail "restart failed (rollback)" 3
    log "rollback complete; verify via:"
    log "  $0 post-verify --image-tag 0.5.1-pre-cutover --manifest-version 0.5.1-pre-cutover --boot-record-count 10"
    ;;

  *)
    err "unknown subcommand: $SUBCOMMAND"
    usage >&2
    exit 1
    ;;
esac
