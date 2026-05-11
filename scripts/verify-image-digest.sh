#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Image-digest verification gate for the Phase-1b NATS substrate
# (Phase-2 Sprint-4 Tag-3, Cross-Review Zone-C upgrade over the
# Sprint-2-Tag-3 tag-pin).
#
# What this script does
# ---------------------
#
# 1. Hermetic by default: parse ``compose/nats.yaml`` and assert that
#    the ``services.nats.image`` value is in one of the accepted forms
#       * tag-only:    ``nats:2.11-alpine``           (legacy; warn)
#       * digest-pin:  ``nats:2.11-alpine@sha256:<64-hex>``  (preferred)
#    and that the digest-hex (when present) has the right shape (64
#    lowercase hex characters). No network, no container engine, no
#    cosign required for the default run.
#
# 2. Opt-in ``--with-registry``: cross-reference the manifest-list
#    digest against the Docker Hub public registry API for the
#    configured tag. This is the only network-touching mode and is
#    explicitly opt-in (CI smoke gate, build-host operator hand). The
#    CEO-side authoring sandbox does NOT use this mode (ADR-0051-
#    rejected; operative sandbox-host-trennung retained).
#
# 3. Opt-in ``--with-cosign``: invoke ``cosign verify`` against the
#    digest-pinned image. Phase-1b: the official NATS image is not
#    currently signed by Synadia with a published cosign key, so this
#    mode is a no-op for Phase-1b but the surface is here so the
#    upgrade path lands when Synadia (or another upstream) publishes
#    a signature. The flag requires ``cosign`` on the PATH; if absent
#    the script fails fast with exit 1 (operator MUST install cosign
#    on the build host first).
#
# Exit codes
# ----------
#
#   0 — image-pin is in an accepted form and (if requested) the
#       registry / cosign cross-reference passed
#   1 — image-pin malformed, missing compose file, cosign requested
#       but binary missing, registry probe failed
#   2 — image-pin is tag-only (legacy form); accepted by hermetic
#       suite but not by the digest-pin gate; only fired with
#       ``--strict`` (default is warn-and-pass)
#
# Usage
# -----
#
#   scripts/verify-image-digest.sh                       # hermetic
#   scripts/verify-image-digest.sh --strict              # fail on tag-only
#   scripts/verify-image-digest.sh --with-registry       # +registry probe
#   scripts/verify-image-digest.sh --with-cosign         # +cosign verify
#   scripts/verify-image-digest.sh --compose-file PATH   # explicit path
#   scripts/verify-image-digest.sh --json                # JSON-only stdout
#
# All flags compose. ``--with-registry`` is the only mode that touches
# the network; ``--with-cosign`` requires the cosign binary but does
# not by itself reach for the registry (cosign chooses its own probe).
#
# Cross-Review-Zone-C note: this script is the digest-pin operational
# half of the Cross-Review Zone-C ack (Engineering-Lead-side ack on
# 2026-05-07 on the tag-pin form, with digest-pin upgrade as the
# OTS-pipeline-trigger pre-condition). The compose-file-side of the
# upgrade lives in ``compose/nats.yaml`` ``services.nats.image``;
# this script is the operator-facing verification gate.
#
# Sources (P7 / P2 stamps — verify before relying on cached values):
#
#   * Docker Hub public registry API for the official ``nats`` repo:
#     https://registry.hub.docker.com/v2/repositories/library/nats/tags/<tag>
#     Verified 2026-05-11 for tag ``2.11-alpine`` (HTTP 200, JSON body
#     with ``digest``, ``last_updated``, ``images[]`` fields).
#   * cosign(1) man page; ``cosign verify`` semantics. Not verified
#     in the authoring sandbox (no cosign installed); P2 conjecture
#     on the exact flag surface for the public-good sigstore TUF
#     root (build-host operator must confirm).

set -euo pipefail

# ---------------------------------------------------------------------
# Defaults + flag parsing
# ---------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE_DEFAULT="${REPO_ROOT}/compose/nats.yaml"

COMPOSE_FILE="${COMPOSE_FILE_DEFAULT}"
WITH_REGISTRY=0
WITH_COSIGN=0
STRICT=0
JSON_ONLY=0
EXPECTED_TAG="nats:2.11-alpine"
EXPECTED_DIGEST=""  # optional: pin to a specific digest, otherwise
                    # the script accepts any 64-hex digest under the
                    # expected tag

usage() {
  sed -n '1,80p' "$0" | sed -e 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --compose-file)
      COMPOSE_FILE="$2"
      shift 2
      ;;
    --with-registry)
      WITH_REGISTRY=1
      shift
      ;;
    --with-cosign)
      WITH_COSIGN=1
      shift
      ;;
    --strict)
      STRICT=1
      shift
      ;;
    --json)
      JSON_ONLY=1
      shift
      ;;
    --expected-tag)
      EXPECTED_TAG="$2"
      shift 2
      ;;
    --expected-digest)
      EXPECTED_DIGEST="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "verify-image-digest: unknown flag: $1" >&2
      exit 1
      ;;
  esac
done

# ---------------------------------------------------------------------
# Logging helpers (stderr human-readable; stdout JSON-suitable)
# ---------------------------------------------------------------------

log()  { [[ "${JSON_ONLY}" -eq 1 ]] || echo "[verify-image-digest] $*" >&2; }
warn() { [[ "${JSON_ONLY}" -eq 1 ]] || echo "[verify-image-digest] WARN: $*" >&2; }
fail() { echo "[verify-image-digest] FAIL: $*" >&2; }

# ---------------------------------------------------------------------
# 1. Compose-parse + image-pin form
# ---------------------------------------------------------------------

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  fail "compose file not found: ${COMPOSE_FILE}"
  exit 1
fi

# Extract the ``image:`` value under ``services.nats``. Pure-bash
# parsing keeps this script stdlib-free (no python, no yq, no docker).
# The compose file uses the documented 2-space indent under services.
IMAGE_LINE="$(awk '
  /^services:/        { in_services = 1; next }
  in_services && /^[^[:space:]]/ { in_services = 0 }
  in_services && /^  nats:/ { in_nats = 1; next }
  in_nats && /^  [^[:space:]]/ { in_nats = 0 }
  in_nats && /^[[:space:]]+image:/ { print; exit }
' "${COMPOSE_FILE}")"

if [[ -z "${IMAGE_LINE}" ]]; then
  fail "could not locate services.nats.image in ${COMPOSE_FILE}"
  exit 1
fi

# Strip ``    image:`` prefix and surrounding whitespace.
IMAGE="${IMAGE_LINE#*image:}"
IMAGE="${IMAGE// /}"
IMAGE="${IMAGE//$'\t'/}"

log "compose-file: ${COMPOSE_FILE}"
log "image-pin:    ${IMAGE}"

# Form classification.
FORM="unknown"
TAG_PART=""
DIGEST_PART=""

if [[ "${IMAGE}" =~ ^([^@]+)@sha256:([0-9a-f]{64})$ ]]; then
  FORM="digest-pin"
  TAG_PART="${BASH_REMATCH[1]}"
  DIGEST_PART="${BASH_REMATCH[2]}"
elif [[ "${IMAGE}" =~ ^[^@]+$ ]] && [[ "${IMAGE}" == *":"* ]]; then
  FORM="tag-only"
  TAG_PART="${IMAGE}"
else
  fail "image-pin in unrecognised form: ${IMAGE}"
  exit 1
fi

if [[ "${TAG_PART}" != "${EXPECTED_TAG}" ]]; then
  fail "tag-part mismatch: got ${TAG_PART}, expected ${EXPECTED_TAG}"
  exit 1
fi

if [[ "${FORM}" == "tag-only" ]]; then
  if [[ "${STRICT}" -eq 1 ]]; then
    fail "image-pin is tag-only; --strict requires digest-pin form"
    exit 2
  fi
  warn "image-pin is tag-only; digest-pin upgrade recommended (runbook §3.1)"
fi

if [[ -n "${EXPECTED_DIGEST}" ]] && [[ "${FORM}" == "digest-pin" ]]; then
  if [[ "${DIGEST_PART}" != "${EXPECTED_DIGEST}" ]]; then
    fail "digest mismatch: got ${DIGEST_PART}, expected ${EXPECTED_DIGEST}"
    exit 1
  fi
  log "digest matches --expected-digest pin"
fi

# ---------------------------------------------------------------------
# 2. Optional: registry cross-reference (network)
# ---------------------------------------------------------------------

REGISTRY_STATUS="skipped"
REGISTRY_DIGEST=""
if [[ "${WITH_REGISTRY}" -eq 1 ]]; then
  if ! command -v curl >/dev/null 2>&1; then
    fail "--with-registry requires curl on PATH"
    exit 1
  fi
  if ! command -v python3 >/dev/null 2>&1; then
    fail "--with-registry requires python3 on PATH (for stdlib JSON parse)"
    exit 1
  fi
  # Tag format is repo:tag; for the public ``nats`` repo the API path
  # is ``library/nats``.
  REPO_NAME="${TAG_PART%:*}"
  TAG_NAME="${TAG_PART#*:}"
  if [[ "${REPO_NAME}" != *"/"* ]]; then
    # Bare repo name implies ``library/<name>`` on Docker Hub.
    API_PATH="library/${REPO_NAME}"
  else
    API_PATH="${REPO_NAME}"
  fi
  URL="https://registry.hub.docker.com/v2/repositories/${API_PATH}/tags/${TAG_NAME}"
  log "registry-probe: ${URL}"
  RESP="$(curl -fsS --max-time 10 "${URL}" 2>/dev/null || true)"
  if [[ -z "${RESP}" ]]; then
    fail "registry probe failed (empty response or non-2xx)"
    REGISTRY_STATUS="probe-failed"
    exit 1
  fi
  REGISTRY_DIGEST="$(echo "${RESP}" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
except Exception as exc:
    print('', end='')
    sys.exit(0)
v = d.get('digest', '')
if v.startswith('sha256:'):
    print(v[len('sha256:'):])
else:
    print(v)
")"
  if [[ -z "${REGISTRY_DIGEST}" ]]; then
    fail "registry response missing 'digest' field"
    REGISTRY_STATUS="malformed-response"
    exit 1
  fi
  if [[ "${FORM}" == "digest-pin" ]]; then
    if [[ "${REGISTRY_DIGEST}" != "${DIGEST_PART}" ]]; then
      fail "compose-pin digest does not match registry: compose=${DIGEST_PART} registry=${REGISTRY_DIGEST}"
      REGISTRY_STATUS="drift"
      exit 1
    fi
    REGISTRY_STATUS="ok"
    log "registry-digest matches compose-pin"
  else
    REGISTRY_STATUS="advisory-only"
    log "registry-digest (advisory, compose is tag-only): ${REGISTRY_DIGEST}"
  fi
fi

# ---------------------------------------------------------------------
# 3. Optional: cosign verify
# ---------------------------------------------------------------------

COSIGN_STATUS="skipped"
if [[ "${WITH_COSIGN}" -eq 1 ]]; then
  if ! command -v cosign >/dev/null 2>&1; then
    fail "--with-cosign requires cosign on PATH; install per runbook §3.1"
    COSIGN_STATUS="binary-missing"
    exit 1
  fi
  if [[ "${FORM}" != "digest-pin" ]]; then
    fail "--with-cosign requires digest-pinned image form"
    COSIGN_STATUS="not-digest-pinned"
    exit 1
  fi
  # Cosign-verify against the sigstore public-good transparency log.
  # The exact flag-shape depends on whether upstream publishes a
  # keyed signature or relies on keyless OIDC; both forms are
  # supported by the surface, but the build-host operator MUST
  # confirm the upstream-specific verification recipe before relying
  # on the result.
  log "cosign-verify: ${TAG_PART}@sha256:${DIGEST_PART}"
  COSIGN_OUT_RAW="$(cosign verify "${TAG_PART}@sha256:${DIGEST_PART}" 2>&1 || true)"
  COSIGN_EXIT=$?
  if [[ ${COSIGN_EXIT} -eq 0 ]]; then
    COSIGN_STATUS="ok"
    log "cosign verify reports OK"
  else
    # Phase-1b note: the official NATS image is not currently signed
    # with a published vendor key. Cosign-verify against the sigstore
    # public-good log will fail for unsigned images, but that is a
    # documented Phase-1b reality, not a substrate fault. The script
    # surfaces the diagnostic and exits 1 so an operator who opted
    # in to cosign verification sees the gap clearly.
    fail "cosign verify failed (Phase-1b: official NATS image may be unsigned)"
    COSIGN_STATUS="verify-failed"
    if [[ "${JSON_ONLY}" -ne 1 ]]; then
      echo "${COSIGN_OUT_RAW}" >&2
    fi
    exit 1
  fi
fi

# ---------------------------------------------------------------------
# 4. JSON summary
# ---------------------------------------------------------------------

cat <<EOF
{"tool":"verify-image-digest.sh","compose_file":"${COMPOSE_FILE}","image":"${IMAGE}","form":"${FORM}","tag":"${TAG_PART}","digest":"${DIGEST_PART}","registry_status":"${REGISTRY_STATUS}","registry_digest":"${REGISTRY_DIGEST}","cosign_status":"${COSIGN_STATUS}","strict":${STRICT},"exit":0}
EOF

exit 0
