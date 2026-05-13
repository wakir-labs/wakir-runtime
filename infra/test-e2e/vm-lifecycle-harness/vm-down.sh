#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-9 Tag-5 — Disposable Wakir-Pilot Acceptance-Gate VM
#                          teardown (vm-down).
#
# Reads the state file written by vm-up.sh, parses the
# WAKIR_E2E_DESTROY_HANDLE, and tears down the VM. Idempotent: an
# already-gone VM is a no-op success. Always exits 0 unless the destroy
# explicitly fails on a still-present resource — we want this safe to
# `trap EXIT`.

set -u

: "${WAKIR_E2E_STATE_DIR:=/var/lib/wakir-e2e}"
STATE_FILE="$WAKIR_E2E_STATE_DIR/vm.env"

log() { echo "[vm-down] $*" >&2; }

if [[ ! -f "$STATE_FILE" ]]; then
  log "no state file at $STATE_FILE; nothing to tear down"
  exit 0
fi

# shellcheck disable=SC1090
. "$STATE_FILE"

handle="${WAKIR_E2E_DESTROY_HANDLE:-}"
if [[ -z "$handle" ]]; then
  log "state file present but DESTROY_HANDLE empty; nothing to do"
  exit 0
fi

provider="${handle%%:*}"
rest="${handle#*:}"

case "$provider" in
  qemu)
    # rest = pidfile:disk:ign
    IFS=':' read -r pidfile disk ign <<<"$rest"
    if [[ -f "$pidfile" ]]; then
      pid=$(cat "$pidfile" 2>/dev/null || true)
      if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
        log "stopping qemu pid=$pid"
        kill -TERM "$pid" 2>/dev/null || true
        for _ in 1 2 3 4 5 6 7 8 9 10; do
          if ! kill -0 "$pid" 2>/dev/null; then break; fi
          sleep 1
        done
        if kill -0 "$pid" 2>/dev/null; then
          log "qemu pid=$pid did not exit; SIGKILL"
          kill -KILL "$pid" 2>/dev/null || true
        fi
      else
        log "pidfile present but pid not running; cleaning up"
      fi
      rm -f "$pidfile"
    else
      log "no pidfile at $pidfile; nothing to kill"
    fi
    [[ -f "$disk" ]] && rm -f "$disk" && log "removed disk $disk"
    [[ -f "$ign" ]]  && rm -f "$ign"  && log "removed ignition $ign"
    ;;
  proxmox)
    # rest = clone_vmid
    clone_id="$rest"
    if command -v qm >/dev/null 2>&1; then
      log "stopping proxmox VM $clone_id"
      qm stop "$clone_id" 2>/dev/null || true
      log "destroying proxmox VM $clone_id"
      qm destroy "$clone_id" --purge 1 2>/dev/null || \
        log "WARNING: qm destroy $clone_id returned non-zero (already gone?)"
    else
      log "qm not on PATH; cannot tear down proxmox VM $clone_id"
    fi
    ;;
  *)
    log "unknown destroy handle provider: $provider; nothing to do"
    ;;
esac

# Remove state so subsequent vm-up.sh starts fresh.
rm -f "$STATE_FILE"
log "teardown complete"
exit 0
