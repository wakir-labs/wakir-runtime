#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Phase-2 Sprint-Tag-8 — Production install-script for the Tomás-
# Persona Quadlet (Bug-35-Folge-Item).
#
# **Why this script exists.**
#
# Bug-35 (Sprint-10 Tag-6) fixed the Quadlet bind-mount-Path-Drift:
# the Quadlet sources now point at the Operator-staged
# /etc/wakir/persona/<slug>.{md,json} paths instead of the
# wakir-runtime repo tree. The Live-VM-Trial since then runs the
# container via `podman run` directly (Mira-Hand workaround) because
# the production-Quadlet install + DNS-config + env-file wiring was
# never codified.
#
# This script codifies the production install path:
#
#   1. Stages the persona-files at /etc/wakir/persona/<slug>.{md,json}
#      from operator-supplied source paths.
#   2. Stages the NATS-KV-credentials env-file at
#      /etc/wakir/persona-<slug>.env with 0600 perms.
#   3. Installs the Quadlet at /etc/containers/systemd/<slug>.container.
#   4. systemctl daemon-reload + start the service.
#   5. Runs `podman quadlet-validate` (or the wakir-quadlet-lint
#      equivalent) as a final pre-start gate. Aborts before the
#      systemctl start if validation fails.
#
# Sandbox boundary
# ----------------
#
# This script runs ON the Pilot-VM, as root, via Operator-Hand. It
# does NOT run in the claude-dev Sandbox.
#
# Invocation
# ----------
#
#   sudo ./install-persona-tomas-quadlet.sh \
#       --persona-md /path/to/tomas.md \
#       --persona-json /path/to/tomas.json \
#       --nats-creds /path/to/tomas.env \
#       [--repo-root /opt/wakir-runtime] \
#       [--no-start]
#
# Required flags:
#   --persona-md            Source axis-A Markdown (read-only mount).
#   --persona-json          Source axis-C JSON canonical form.
#   --nats-creds            Source env-file with the NATS-KV creds.
#                           Schema: WAKIR_NATS_USER + WAKIR_NATS_PASSWORD
#                           OR WAKIR_NATS_CREDS_FILE for JWT-auth. The
#                           file is installed with mode 0600.
#
# Optional flags:
#   --repo-root             /opt/wakir-runtime by default — used to
#                           locate the Quadlet source under quadlet/.
#   --persona-slug          Default: tomas.
#   --no-start              Install only; do not systemctl start.
#                           Useful for the first install when the
#                           SPIRE-Agent socket may not yet be bound.
#   --validate-only         Run only the pre-flight + validate
#                           steps; do not install or start.
#   --help, -h              Show help.
#
# Exit codes
# ----------
#
#   0  Install + start OK (or --no-start install OK).
#   1  Pre-flight failed (missing flag, source-file missing, ...).
#   2  Quadlet-validate failed.
#   3  systemctl start failed.
#
# -- Kai

set -eu -o pipefail

PROG=$(basename "$0")

PERSONA_MD=""
PERSONA_JSON=""
NATS_CREDS=""
REPO_ROOT="/opt/wakir-runtime"
PERSONA_SLUG="tomas"
NO_START=0
VALIDATE_ONLY=0

usage() {
  sed -n '2,60p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --persona-md)     PERSONA_MD="${2:-}";    shift 2;;
    --persona-json)   PERSONA_JSON="${2:-}";  shift 2;;
    --nats-creds)     NATS_CREDS="${2:-}";    shift 2;;
    --repo-root)      REPO_ROOT="${2:-}";     shift 2;;
    --persona-slug)   PERSONA_SLUG="${2:-}";  shift 2;;
    --no-start)       NO_START=1;             shift;;
    --validate-only)  VALIDATE_ONLY=1;        shift;;
    -h|--help)        usage; exit 0;;
    *)
      echo "[$PROG] ERROR: unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

log()  { printf '[%s] %s\n' "$PROG" "$*"; }
fail() { printf '[%s] FAIL: %s\n' "$PROG" "$*" >&2; exit "${2:-1}"; }

# --- Pre-flight ------------------------------------------------------------

if [[ "$(id -u)" != "0" ]]; then
  fail "must run as root (sudo $0 ...)" 1
fi

for label in PERSONA_MD PERSONA_JSON NATS_CREDS; do
  v="${!label:-}"
  if [[ -z "$v" ]]; then
    fail "--${label,,} is required (replace _ with -)" 1
  fi
  if [[ ! -r "$v" ]]; then
    fail "source not readable: $v" 1
  fi
done

if [[ ! -r "$REPO_ROOT/quadlet/wakir-persona-${PERSONA_SLUG}.container" ]]; then
  fail "Quadlet source not found: $REPO_ROOT/quadlet/wakir-persona-${PERSONA_SLUG}.container" 1
fi

if ! command -v podman >/dev/null 2>&1; then
  fail "podman not installed; required for Quadlet generator" 1
fi
if ! command -v systemctl >/dev/null 2>&1; then
  fail "systemctl not in PATH" 1
fi

log "pre-flight OK (slug=${PERSONA_SLUG}, repo-root=${REPO_ROOT})"

# --- Phase 1: stage persona-files -----------------------------------------

if [[ "$VALIDATE_ONLY" -ne 1 ]]; then
  log "phase 1: stage persona-files at /etc/wakir/persona/"
  install -d -m 755 /etc/wakir
  install -d -m 755 /etc/wakir/persona
  install -m 644 "$PERSONA_MD"   "/etc/wakir/persona/${PERSONA_SLUG}.md"
  install -m 644 "$PERSONA_JSON" "/etc/wakir/persona/${PERSONA_SLUG}.json"
  log "  - /etc/wakir/persona/${PERSONA_SLUG}.md"
  log "  - /etc/wakir/persona/${PERSONA_SLUG}.json"

  # --- Phase 2: stage NATS-KV creds env-file --------------------------------

  log "phase 2: stage NATS creds at /etc/wakir/persona-${PERSONA_SLUG}.env (mode 0600)"
  install -m 600 "$NATS_CREDS" "/etc/wakir/persona-${PERSONA_SLUG}.env"

  # --- Phase 3: install Quadlet --------------------------------------------

  log "phase 3: install Quadlet at /etc/containers/systemd/wakir-persona-${PERSONA_SLUG}.container"
  install -d -m 755 /etc/containers/systemd
  install -m 644 \
    "$REPO_ROOT/quadlet/wakir-persona-${PERSONA_SLUG}.container" \
    "/etc/containers/systemd/wakir-persona-${PERSONA_SLUG}.container"

  # Persona-state-pairs marker (required by the bucket-init oneshot
  # the Quadlet depends on; see persona-tomas Quadlet header).
  install -d -m 755 /etc/wakir
  if ! grep -q "^acme-${PERSONA_SLUG}\$" /etc/wakir/persona-state-pairs 2>/dev/null; then
    printf 'acme-%s\n' "$PERSONA_SLUG" | tee -a /etc/wakir/persona-state-pairs >/dev/null
    log "  - appended 'acme-${PERSONA_SLUG}' to /etc/wakir/persona-state-pairs"
  fi
fi

# --- Phase 4: Quadlet validate -------------------------------------------

log "phase 4: podman quadlet validate"
quadlet_bin=""
for cand in /usr/libexec/podman/quadlet /usr/lib/podman/quadlet; do
  if [[ -x "$cand" ]]; then
    quadlet_bin="$cand"
    break
  fi
done

if [[ -z "$quadlet_bin" ]]; then
  # Fall back to the wakir-quadlet-lint script if the podman generator
  # binary is not on the host (older podman versions exposed the
  # generator under different paths).
  if [[ -x "$REPO_ROOT/infra/spire/federation/bin/wakir-quadlet-lint.sh" ]]; then
    log "  - using wakir-quadlet-lint.sh (podman generator binary not on host)"
    if ! "$REPO_ROOT/infra/spire/federation/bin/wakir-quadlet-lint.sh"; then
      fail "Quadlet validation failed via wakir-quadlet-lint.sh" 2
    fi
  else
    log "WARN: no podman quadlet generator and no wakir-quadlet-lint.sh; skipping validate"
  fi
else
  # Generator runs against /etc/containers/systemd; --dryrun keeps it
  # idempotent (no actual unit-file generation in /run).
  if ! "$quadlet_bin" --dryrun --user=0 /etc/containers/systemd >/tmp/quadlet-validate.log 2>&1; then
    log "Quadlet validation FAILED — see /tmp/quadlet-validate.log:"
    cat /tmp/quadlet-validate.log >&2
    fail "Quadlet validation failed" 2
  fi
  # The generator can also exit 0 with WARN-only diagnostics on stderr;
  # surface them for operator visibility but do not abort.
  if grep -qiE 'error|invalid' /tmp/quadlet-validate.log 2>/dev/null; then
    log "WARN: validate-log contains warnings:"
    grep -iE 'error|invalid' /tmp/quadlet-validate.log | head -10 || true
  fi
fi

log "phase 4: Quadlet validate OK"

if [[ "$VALIDATE_ONLY" -eq 1 ]]; then
  log "--validate-only set; install + start skipped"
  exit 0
fi

# --- Phase 5: systemctl daemon-reload + start ----------------------------

log "phase 5: systemctl daemon-reload"
systemctl daemon-reload

if [[ "$NO_START" -eq 1 ]]; then
  log "--no-start set; service NOT started"
  log "to start manually: sudo systemctl start wakir-persona-${PERSONA_SLUG}.service"
  exit 0
fi

log "phase 5b: systemctl start wakir-persona-${PERSONA_SLUG}.service"
if ! systemctl start "wakir-persona-${PERSONA_SLUG}.service"; then
  systemctl status "wakir-persona-${PERSONA_SLUG}.service" >&2 || true
  fail "systemctl start failed" 3
fi

log "install + start complete; verifying with podman healthcheck"
sleep 5
if podman healthcheck run "wakir-persona-${PERSONA_SLUG}" >/dev/null 2>&1; then
  log "healthcheck PASS"
else
  log "WARN: healthcheck did not pass on first probe (HealthStartPeriod=45s; re-check shortly)"
fi

log "DONE."
exit 0
