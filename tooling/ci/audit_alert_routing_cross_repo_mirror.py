#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Tag-58 Alert-Routing-Spec Cross-Repo-Mirror Audit (Noa SRE).

Context
-------

Tag-57 (PR #368) shipped the watch-day-cron-pre-fire-probe. Stage C
of that probe runs an Alert-Routing dry-run against
``wakir-runtime``. Pre-KW-24 closeout requires that the
*Alert-Routing-Spec* — the source of truth for which Prometheus
alert routes to which Mira-Notify channel — is byte-canonical
identical (modulo SPDX/banner allowlist) between this BUSL-side
runtime repo and the Apache-2.0 + CC-BY-side ``wakir-protocol``
repo where the contract surface lives.

A silent drift between the two repos is a cross-repo bug class
exactly analogous to the Wirelang-schema drift class that the
sibling ``cross-repo-drift-audit`` workflow guards. The Tag-58
audit closes that hole specifically for the alert-routing
substance:

* The Pre-Mortem Notify-Catalog (``docs/observability/
  pre-mortem-failure-mode-notify-catalog.md``).
* The Phase-3 Marathon Backend-Alerting-Rules
  (``dashboards/phase-3-marathon-alerts.yaml``).
* The Phase-3 Marathon SLO Burn-Rate Alerts
  (``dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml``).
* The Alert-Rule → Mira-Notify Bridge mapping table
  (``scripts/observability/alert-rule-to-mira-notify-bridge.py``,
  ``ALERT_CATALOG`` constant).

Until the Cut-3 sync is complete, the protocol-side mirror paths
may not yet exist. The audit treats *missing-on-protocol* as a
distinct verdict class (``missing-protocol``) and surfaces it in
the same MIRROR-OK / MIRROR-DRIFT verdict table.

Canonical-form normalisation
----------------------------

Byte-for-byte SHA-256 is too brittle: SPDX headers differ between
``Apache-2.0`` (protocol) and ``BUSL-1.1`` (runtime), and a
copyright banner may carry a different year-of-update. The
canonical form strips those headers from both sides before
hashing so that *semantic* drift surfaces but cosmetic license-
banner drift does not.

The normalisation is intentionally narrow:

  1. Drop a leading SPDX-License-Identifier line.
  2. Drop a leading SPDX-FileCopyrightText line.
  3. Drop a leading ``Copyright (c) ...`` comment line.
  4. Drop blank lines that immediately follow steps 1-3.
  5. Strip trailing whitespace on every line, drop trailing
     blank lines.

It does NOT:

  * Strip in-line copyright comments deeper in the file.
  * Strip docstrings or doc-headers.
  * Strip any content-bearing comment.

That narrowness is deliberate: a wider normaliser would mask
real drift (a removed paragraph in the notify-catalog markdown,
a renamed alert rule).

Allowlist
---------

The allowlist file ``.alert-routing-cross-repo-allowlist.yaml``
lives at repo root. Initial file is **empty by design**: we
observe the baseline drift first, then admit waivers in a
follow-up PR after Tomás Cross-Review-Zone-I review.

Format::

    allow:
      - runtime: docs/observability/pre-mortem-failure-mode-notify-catalog.md
        protocol: docs/observability/pre-mortem-failure-mode-notify-catalog.md
        reason: <free text>

A malformed allowlist is a soft-fail in audit-mode (the CI step
surfaces a warning and proceeds as if empty).

CLI
---

::

    audit_alert_routing_cross_repo_mirror.py \\
        --runtime-root <runtime-clone-root> \\
        --protocol-root <protocol-clone-root> \\
        [--allowlist <yaml-file>] \\
        [--format json|markdown|github] \\
        [--enforce]

Exit codes
----------

* ``0`` — MIRROR-OK, OR drift observed under ``--audit-only``
  (the default).
* ``1`` — MIRROR-DRIFT detected with ``--enforce``.
* ``2`` — internal/invocation error (missing roots, etc.).

Audit/enforce posture
---------------------

This is the *introduction* cut. By default ``--audit-only`` is
active: the script always exits 0 on drift and surfaces the
verdict for human review. The ``--enforce`` flag flips the gate
to a CI-fatal mode once the baseline allowlist is seeded and the
Tomás cross-review of the WAT-side semantics has signed off.

Hermetic discipline
-------------------

stdlib only. PyYAML is consumed *optionally* for the allowlist
loader and the YAML alert-rule files; when absent the script
falls back to a minimal hand-parser sufficient for the
allowlist schema and the small YAML subset used by the alert
files (which the Cosign/Quadlet test substrate already proves is
parseable with a narrow loader).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Iterable, Sequence


# ---------------------------------------------------------------------------
# Canonical mirror-pair table
# ---------------------------------------------------------------------------

# Each entry is (runtime-relative-path, protocol-relative-path,
# normaliser-class). The normaliser-class controls which header-
# stripping rule set applies to the file (Python / YAML / Markdown).
#
# Selection rationale (Tag-58 Pre-KW-24 scope):
#
#   * pre-mortem-failure-mode-notify-catalog.md — the Notify-Catalog
#     itself; the source of truth for routing semantics per Henrik
#     Pre-Mortem Tag-44.
#   * phase-3-marathon-alerts.yaml — Backend-Alerting-Rules; the
#     Prometheus-side authoritative rule file.
#   * phase-3-marathon-slo-burn-rate-alerts.yaml — SLO Burn-Rate
#     companion rule set; routes share the same Mira-Notify
#     receiver tree.
#   * alert-rule-to-mira-notify-bridge.py — the runtime-side adapter;
#     the ``ALERT_CATALOG`` constant in this module is the wiring
#     between Prometheus alertname and Mira-Notify failure_mode_id.
#
# Keep this table small (≤ 10 rows). Mirror-pair audits trade
# breadth for tractability; new entries require Tomás Zone-I
# review.

NORMALISER_PY = "python"
NORMALISER_YAML = "yaml"
NORMALISER_MARKDOWN = "markdown"


@dataclasses.dataclass(frozen=True)
class MirrorPair:
    runtime_path: str
    protocol_path: str
    normaliser: str
    description: str


MIRROR_PAIRS: tuple[MirrorPair, ...] = (
    MirrorPair(
        runtime_path="docs/observability/pre-mortem-failure-mode-notify-catalog.md",
        protocol_path="docs/observability/pre-mortem-failure-mode-notify-catalog.md",
        normaliser=NORMALISER_MARKDOWN,
        description="Pre-Mortem Notify-Catalog (Tag-45 Noa)",
    ),
    MirrorPair(
        runtime_path="dashboards/phase-3-marathon-alerts.yaml",
        protocol_path="dashboards/phase-3-marathon-alerts.yaml",
        normaliser=NORMALISER_YAML,
        description="Phase-3 Marathon Backend-Alerting-Rules",
    ),
    MirrorPair(
        runtime_path="dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
        protocol_path="dashboards/phase-3-marathon-slo-burn-rate-alerts.yaml",
        normaliser=NORMALISER_YAML,
        description="Phase-3 Marathon SLO Burn-Rate Alerts",
    ),
    MirrorPair(
        runtime_path="scripts/observability/alert-rule-to-mira-notify-bridge.py",
        protocol_path="scripts/observability/alert-rule-to-mira-notify-bridge.py",
        normaliser=NORMALISER_PY,
        description="Alert-Rule → Mira-Notify bridge (ALERT_CATALOG)",
    ),
)


# ---------------------------------------------------------------------------
# Verdict constants (shared with workflow and tests)
# ---------------------------------------------------------------------------

VERDICT_MIRROR_OK = "MIRROR-OK"
VERDICT_MIRROR_DRIFT = "MIRROR-DRIFT"

STATUS_OK = "ok"
STATUS_DRIFT = "DRIFT"
STATUS_DRIFT_ALLOWED = "drift-allowed"
STATUS_MISSING_RUNTIME = "missing-runtime"
STATUS_MISSING_PROTOCOL = "missing-protocol"
STATUS_MISSING_BOTH = "missing-both"


# ---------------------------------------------------------------------------
# Canonicaliser
# ---------------------------------------------------------------------------

_SPDX_LICENSE_RE = re.compile(r"^\s*[#!/<\-* ]*\s*SPDX-License-Identifier\s*:", re.IGNORECASE)
_SPDX_COPYRIGHT_RE = re.compile(r"^\s*[#!/<\-* ]*\s*SPDX-FileCopyrightText\s*:", re.IGNORECASE)
_PLAIN_COPYRIGHT_RE = re.compile(
    r"^\s*[#!/<\-* ]*\s*Copyright\s*\(c\)\s*\d{4}", re.IGNORECASE
)


def _is_header_line(line: str) -> bool:
    """Return True if ``line`` is an SPDX/copyright header line.

    The matcher is intentionally permissive on the comment-prefix:
    Python ``#``, YAML ``#``, Markdown HTML-comment ``<!--`` and a
    plain leading whitespace are all accepted.
    """
    return bool(
        _SPDX_LICENSE_RE.match(line)
        or _SPDX_COPYRIGHT_RE.match(line)
        or _PLAIN_COPYRIGHT_RE.match(line)
    )


def canonicalise(content: bytes, normaliser: str) -> bytes:
    """Return the canonical-form bytes for ``content``.

    The normaliser is currently shared across all three classes
    (Python / YAML / Markdown) — the SPDX-header line shape is
    identical in each. The ``normaliser`` argument is preserved
    so the function signature remains stable when class-specific
    rules grow.
    """
    text = content.decode("utf-8", errors="replace")
    lines = text.splitlines()

    # Strip top-of-file SPDX/copyright headers and the blank
    # lines that immediately follow them. We walk from the top
    # until we hit the first non-header, non-blank line.
    i = 0
    while i < len(lines):
        ln = lines[i]
        if _is_header_line(ln):
            i += 1
            continue
        if ln.strip() == "" and i < 8:
            # Tolerate up to a few blank lines at top while we are
            # still in the banner region. The bound (8) keeps us
            # from chewing into legitimate empty-lead bodies on
            # weirdly formatted files.
            i += 1
            continue
        break

    body = lines[i:]

    # Strip trailing whitespace per line; drop trailing blank lines.
    body = [ln.rstrip() for ln in body]
    while body and body[-1] == "":
        body.pop()

    canonical = "\n".join(body) + "\n" if body else ""
    return canonical.encode("utf-8")


def sha256_canonical(content: bytes, normaliser: str) -> str:
    """Return the SHA-256 of the canonical-form bytes (hex)."""
    return hashlib.sha256(canonicalise(content, normaliser)).hexdigest()


# ---------------------------------------------------------------------------
# Allowlist loader (stdlib YAML subset; PyYAML used when present)
# ---------------------------------------------------------------------------


def _load_allowlist_with_pyyaml(path: Path) -> tuple[set[tuple[str, str]], str | None]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return set(), "no-pyyaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        return set(), f"malformed: {exc}"
    entries = (data or {}).get("allow") or []
    pairs: set[tuple[str, str]] = set()
    for e in entries:
        if not isinstance(e, dict):
            continue
        r = e.get("runtime") or ""
        p = e.get("protocol") or ""
        if r and p:
            pairs.add((r, p))
    return pairs, None


def _load_allowlist_stdlib_minimal(path: Path) -> tuple[set[tuple[str, str]], str | None]:
    """Minimal fallback parser for the allowlist schema.

    Recognises only the two-key shape::

        allow:
          - runtime: <path>
            protocol: <path>
            reason: <text>

    Tolerates comments and blank lines; does not implement
    arbitrary YAML. Sufficient for the bounded allowlist schema.
    """
    pairs: set[tuple[str, str]] = set()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return pairs, f"read-failed: {exc}"

    in_allow = False
    current: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("allow:"):
            in_allow = True
            continue
        if not in_allow:
            continue
        if stripped.startswith("- "):
            if current.get("runtime") and current.get("protocol"):
                pairs.add((current["runtime"], current["protocol"]))
            current = {}
            kv = stripped[2:].split(":", 1)
            if len(kv) == 2:
                current[kv[0].strip()] = kv[1].strip().strip('"').strip("'")
            continue
        if ":" in stripped:
            k, v = stripped.split(":", 1)
            current[k.strip()] = v.strip().strip('"').strip("'")

    if current.get("runtime") and current.get("protocol"):
        pairs.add((current["runtime"], current["protocol"]))

    return pairs, None


def load_allowlist(path: Path | None) -> tuple[set[tuple[str, str]], str | None]:
    """Load the allowlist file.

    Returns a tuple ``(pairs, warning)``. ``warning`` is None on a
    clean load and a free-text reason on a soft-fail (file missing,
    malformed, parser missing). Soft-fail is the contract: the
    caller treats the allowlist as empty.
    """
    if path is None or not path.exists():
        return set(), None
    pairs, warn = _load_allowlist_with_pyyaml(path)
    if warn == "no-pyyaml":
        # Fall back to stdlib parser.
        return _load_allowlist_stdlib_minimal(path)
    return pairs, warn


# ---------------------------------------------------------------------------
# Audit core
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class PairResult:
    pair: MirrorPair
    status: str
    runtime_sha: str
    protocol_sha: str
    runtime_present: bool
    protocol_present: bool


@dataclasses.dataclass(frozen=True)
class AuditResult:
    verdict: str
    ok_count: int
    drift_count: int
    drift_allowed_count: int
    missing_count: int
    results: tuple[PairResult, ...]
    allowlist_warning: str | None


def audit_pair(
    pair: MirrorPair,
    runtime_root: Path,
    protocol_root: Path,
    allowlist: set[tuple[str, str]],
) -> PairResult:
    runtime_abs = runtime_root / pair.runtime_path
    protocol_abs = protocol_root / pair.protocol_path
    runtime_present = runtime_abs.is_file()
    protocol_present = protocol_abs.is_file()

    runtime_sha = ""
    protocol_sha = ""

    if runtime_present:
        runtime_sha = sha256_canonical(runtime_abs.read_bytes(), pair.normaliser)
    if protocol_present:
        protocol_sha = sha256_canonical(protocol_abs.read_bytes(), pair.normaliser)

    if not runtime_present and not protocol_present:
        status = STATUS_MISSING_BOTH
    elif not runtime_present:
        status = STATUS_MISSING_RUNTIME
    elif not protocol_present:
        status = STATUS_MISSING_PROTOCOL
    else:
        if runtime_sha == protocol_sha:
            status = STATUS_OK
        elif (pair.runtime_path, pair.protocol_path) in allowlist:
            status = STATUS_DRIFT_ALLOWED
        else:
            status = STATUS_DRIFT

    return PairResult(
        pair=pair,
        status=status,
        runtime_sha=runtime_sha,
        protocol_sha=protocol_sha,
        runtime_present=runtime_present,
        protocol_present=protocol_present,
    )


def audit(
    runtime_root: Path,
    protocol_root: Path,
    allowlist_path: Path | None = None,
    mirror_pairs: Sequence[MirrorPair] = MIRROR_PAIRS,
) -> AuditResult:
    allowlist, warn = load_allowlist(allowlist_path)

    results: list[PairResult] = []
    ok_count = 0
    drift_count = 0
    drift_allowed_count = 0
    missing_count = 0
    for pair in mirror_pairs:
        r = audit_pair(pair, runtime_root, protocol_root, allowlist)
        results.append(r)
        if r.status == STATUS_OK:
            ok_count += 1
        elif r.status == STATUS_DRIFT:
            drift_count += 1
        elif r.status == STATUS_DRIFT_ALLOWED:
            drift_allowed_count += 1
        else:
            missing_count += 1

    if drift_count == 0 and missing_count == 0:
        verdict = VERDICT_MIRROR_OK
    else:
        verdict = VERDICT_MIRROR_DRIFT

    return AuditResult(
        verdict=verdict,
        ok_count=ok_count,
        drift_count=drift_count,
        drift_allowed_count=drift_allowed_count,
        missing_count=missing_count,
        results=tuple(results),
        allowlist_warning=warn,
    )


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_json(result: AuditResult) -> str:
    payload = {
        "verdict": result.verdict,
        "ok_count": result.ok_count,
        "drift_count": result.drift_count,
        "drift_allowed_count": result.drift_allowed_count,
        "missing_count": result.missing_count,
        "allowlist_warning": result.allowlist_warning,
        "pairs": [
            {
                "runtime_path": r.pair.runtime_path,
                "protocol_path": r.pair.protocol_path,
                "normaliser": r.pair.normaliser,
                "status": r.status,
                "runtime_sha": r.runtime_sha,
                "protocol_sha": r.protocol_sha,
                "runtime_present": r.runtime_present,
                "protocol_present": r.protocol_present,
                "description": r.pair.description,
            }
            for r in result.results
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def render_markdown(result: AuditResult) -> str:
    out: list[str] = []
    out.append("# Alert-Routing-Spec Cross-Repo Mirror Audit (Tag-58)")
    out.append("")
    out.append(f"**Verdict:** `{result.verdict}`")
    out.append("")
    if result.allowlist_warning:
        out.append(f"> allowlist warning: `{result.allowlist_warning}`")
        out.append("")
    out.append(
        "| Status | Runtime path | Protocol path | runtime sha (canonical) | protocol sha (canonical) |"
    )
    out.append("|---|---|---|---|---|")
    for r in result.results:
        rs = (r.runtime_sha[:12] + "…") if r.runtime_sha else "—"
        ps = (r.protocol_sha[:12] + "…") if r.protocol_sha else "—"
        out.append(
            f"| {r.status} | `{r.pair.runtime_path}` | `{r.pair.protocol_path}` | `{rs}` | `{ps}` |"
        )
    out.append("")
    out.append("**Tally**")
    out.append("")
    out.append(f"- ok: {result.ok_count}")
    out.append(f"- drift (un-allowlisted): {result.drift_count}")
    out.append(f"- drift (allowlisted): {result.drift_allowed_count}")
    out.append(f"- missing on either side: {result.missing_count}")
    return "\n".join(out) + "\n"


def render_github_annotations(result: AuditResult) -> list[str]:
    lines: list[str] = []
    for r in result.results:
        if r.status == STATUS_DRIFT:
            lines.append(
                f"::error file={r.pair.runtime_path}::"
                f"alert-routing cross-repo drift: {r.pair.runtime_path} vs "
                f"{r.pair.protocol_path} (canonical sha mismatch)"
            )
        elif r.status in (STATUS_MISSING_RUNTIME, STATUS_MISSING_PROTOCOL, STATUS_MISSING_BOTH):
            lines.append(
                f"::warning file={r.pair.runtime_path}::"
                f"alert-routing cross-repo audit: {r.status}"
            )
    return lines


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audit_alert_routing_cross_repo_mirror",
        description=(
            "Tag-58 cross-repo mirror-audit for the Alert-Routing-Spec "
            "substrate (wakir-runtime ↔ wakir-protocol)."
        ),
    )
    p.add_argument(
        "--runtime-root",
        required=True,
        help="Path to the wakir-runtime checkout root.",
    )
    p.add_argument(
        "--protocol-root",
        required=True,
        help="Path to the wakir-protocol checkout root.",
    )
    p.add_argument(
        "--allowlist",
        default=None,
        help="Path to .alert-routing-cross-repo-allowlist.yaml (defaults to runtime-root/.alert-routing-cross-repo-allowlist.yaml).",
    )
    p.add_argument(
        "--format",
        choices=("json", "markdown", "github"),
        default="markdown",
        help="Output format (default: markdown).",
    )
    p.add_argument(
        "--enforce",
        action="store_true",
        help="Exit non-zero on MIRROR-DRIFT (default: audit-only, exit 0).",
    )
    return p


def main(argv: Iterable[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)

    runtime_root = Path(args.runtime_root).resolve()
    protocol_root = Path(args.protocol_root).resolve()

    if not runtime_root.is_dir():
        print(f"error: --runtime-root not a directory: {runtime_root}", file=sys.stderr)
        return 2
    if not protocol_root.is_dir():
        print(f"error: --protocol-root not a directory: {protocol_root}", file=sys.stderr)
        return 2

    if args.allowlist:
        allowlist_path: Path | None = Path(args.allowlist).resolve()
    else:
        candidate = runtime_root / ".alert-routing-cross-repo-allowlist.yaml"
        allowlist_path = candidate if candidate.exists() else None

    result = audit(runtime_root, protocol_root, allowlist_path)

    if args.format == "json":
        print(render_json(result))
    elif args.format == "github":
        # GitHub-flavoured: annotations then markdown summary.
        for ln in render_github_annotations(result):
            print(ln)
        print(render_markdown(result))
    else:
        print(render_markdown(result))

    if args.enforce and result.verdict == VERDICT_MIRROR_DRIFT:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
