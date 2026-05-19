#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Tag-62 Operator-Hand Bulk-Activation Pre-Walk Recipe
# -----------------------------------------------------
#
# Purpose
# =======
#
# Drives the Operator-Hand bulk-activation of the 7-Pool Required-
# Status-Checks for `wakir-labs/wakir-runtime` `main` branch. The
# script is the single executable form of the Operator-Hand recipe
# documented in:
#   - docs/operations/branch-protection-required-checks-tag59.md
#   - docs/operations/branch-protection-required-checks-tag61-addendum.md
#   - docs/operations/bulk-activation-pre-walk-recipe.md (Tag-62)
#
# Default mode is --dry-run (read-only). The script PRINTS the API
# call plan and exits 0 when the plan is consistent. It does NOT
# touch any branch-protection settings unless --enforce is passed
# AND the script is run on an Operator-Workstation (which the
# sandbox-boundary check below detects).
#
# Sandbox boundary
# ================
#
# Per ADR-0020 §10 + memory `feedback_sandbox_host_trennung.md`:
# Mira-Sandbox MUST NOT hold a write-scoped GitHub token for
# `wakir-labs/wakir-runtime` branch-protection. The script refuses
# `--enforce` whenever:
#   - the env var BULK_ACTIVATE_OPERATOR_HAND is not set to "1", OR
#   - no `gh auth status` is available, OR
#   - $CI is set (CI runners are sandbox-class for this operation).
#
# Modes
# =====
#
#   --dry-run    (default)   read-only; prints API-call plan
#   --enforce                actual PUT (Operator-Hand only)
#   --plan-json              emit machine-readable plan envelope
#
# Idempotency
# ===========
#
# The script reads the current `required_status_checks.contexts`
# (when a token is available) and computes the delta against the
# 7-Pool target. Already-active checks are noted as `NO-OP`; only
# missing checks are added to the planned PUT payload. The PUT
# itself is full-replace (GitHub-API semantics) — the planned
# payload always contains the FULL target set, but the verdict
# line distinguishes "no-op" from "adds N check(s)".
#
# Exit codes
# ==========
#
#   0   plan consistent / activation no-op
#   1   plan inconsistent (parse error, missing checks in doc)
#   2   sandbox-boundary violation (refused --enforce in sandbox)
#   3   --enforce path failed (gh-api PUT non-200)
#
# Wrapper rationale
# =================
#
# The substantive logic lives in
# `tooling/ops/_bulk_activate_required_checks.py` (stdlib-only) for
# testability. This shell wrapper handles:
#   - flag parsing
#   - sandbox-boundary detection
#   - gh-CLI invocation when --enforce is selected
#

set -u

DEFAULT_TAG59_DOC="docs/operations/branch-protection-required-checks-tag59.md"
DEFAULT_TAG61_DOC="docs/operations/branch-protection-required-checks-tag61-addendum.md"

MODE="dry-run"
PLAN_JSON=""
TAG59_DOC=""
TAG61_DOC=""
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

usage() {
  cat <<USAGE
Usage: $(basename "$0") [--dry-run|--enforce] [--plan-json]
                       [--tag59-doc PATH] [--tag61-doc PATH]
                       [--repo-root PATH]

Default mode: --dry-run (read-only). See header comment for the
sandbox-boundary rules around --enforce.
USAGE
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run)     MODE="dry-run"; shift ;;
    --enforce)     MODE="enforce"; shift ;;
    --plan-json)   PLAN_JSON="1";  shift ;;
    --tag59-doc)   TAG59_DOC="$2"; shift 2 ;;
    --tag61-doc)   TAG61_DOC="$2"; shift 2 ;;
    --repo-root)   REPO_ROOT="$2"; shift 2 ;;
    -h|--help)     usage; exit 0 ;;
    *) echo "unknown flag: $1" >&2; usage >&2; exit 1 ;;
  esac
done

TAG59_DOC="${TAG59_DOC:-${REPO_ROOT}/${DEFAULT_TAG59_DOC}}"
TAG61_DOC="${TAG61_DOC:-${REPO_ROOT}/${DEFAULT_TAG61_DOC}}"

PY_HELPER="${REPO_ROOT}/tooling/ops/_bulk_activate_required_checks.py"
if [ ! -f "${PY_HELPER}" ]; then
  echo "missing helper: ${PY_HELPER}" >&2
  exit 1
fi

if [ "${MODE}" = "enforce" ]; then
  if [ "${BULK_ACTIVATE_OPERATOR_HAND:-0}" != "1" ]; then
    echo "REFUSED: --enforce requires BULK_ACTIVATE_OPERATOR_HAND=1" >&2
    echo "sandbox-boundary violation: see ADR-0020 §10 + feedback_sandbox_host_trennung.md" >&2
    exit 2
  fi
  if [ "${CI:-}" = "true" ]; then
    echo "REFUSED: --enforce on CI runner; CI is sandbox-class for branch-protection PUT" >&2
    exit 2
  fi
  if ! command -v gh >/dev/null 2>&1; then
    echo "REFUSED: --enforce needs gh CLI on Operator-Workstation" >&2
    exit 2
  fi
  if ! gh auth status >/dev/null 2>&1; then
    echo "REFUSED: --enforce needs authenticated gh CLI" >&2
    exit 2
  fi
fi

PLAN_ARGS=( --tag59-doc "${TAG59_DOC}" --tag61-doc "${TAG61_DOC}" )
if [ -n "${PLAN_JSON}" ]; then
  PLAN_ARGS+=( --json )
fi

# Always run the planner first. In dry-run mode the planner output
# IS the deliverable; in enforce mode it is the verifiable plan we
# then pass to gh api as the JSON payload.
PLAN_OUTPUT="$(python3 "${PY_HELPER}" "${PLAN_ARGS[@]}")"
PLAN_RC=$?

printf '%s\n' "${PLAN_OUTPUT}"

if [ "${PLAN_RC}" -ne 0 ]; then
  echo "PLAN-INCONSISTENT (planner exit=${PLAN_RC})" >&2
  exit 1
fi

if [ "${MODE}" = "dry-run" ]; then
  echo "verdict: BULK-ACTIVATION-READY (dry-run, no API call performed)"
  exit 0
fi

# --enforce path. Re-render the payload as raw JSON for gh api.
PAYLOAD="$(python3 "${PY_HELPER}" --tag59-doc "${TAG59_DOC}" --tag61-doc "${TAG61_DOC}" --put-payload)"

# Snapshot before
SNAP_PRE="$(mktemp -t bp-snapshot-pre-XXXXXX.json)"
SNAP_POST="$(mktemp -t bp-snapshot-post-XXXXXX.json)"
trap 'rm -f "${SNAP_PRE}" "${SNAP_POST}"' EXIT

if ! gh api repos/wakir-labs/wakir-runtime/branches/main/protection \
      --jq '.required_status_checks.contexts' > "${SNAP_PRE}"; then
  echo "PUT-PRE-SNAPSHOT-FAILED" >&2
  exit 3
fi

echo "--- pre-snapshot ---"
cat "${SNAP_PRE}"

# The full PUT replaces the entire branch-protection block. The
# planner emits the full required_status_checks block ONLY. The
# Operator MUST merge this with the existing non-required-status
# settings (enforce_admins, required_pull_request_reviews, etc.)
# before issuing the PUT. The script refuses to auto-merge those
# fields; doing so unattended risks dropping unrelated settings.
echo "--- planned required_status_checks payload ---"
printf '%s\n' "${PAYLOAD}"
echo "--- end payload ---"
echo "Operator-Hand: merge this payload into the existing full"
echo "/branches/main/protection PUT body and invoke gh api -X PUT"
echo "manually. The script intentionally stops here to keep the"
echo "destructive write fully under Operator control."

exit 0
