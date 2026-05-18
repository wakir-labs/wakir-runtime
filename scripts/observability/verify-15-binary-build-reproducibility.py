#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""15-Binary Build-Reproducibility Audit (Tag-51, Kai).

Context
-------

Tag-45 PR #294 pinned the 15-binary substrate via Cosign-Policy
inventory. Tag-46 PR #298 added the A6 substrate-layer coverage
matrix. Tag-47 PR #307 added the Cosign-Keyless-OIDC-Drift-Probe.
Tag-48 PR #310 added the per-binary SBOM generator
(``generate-15-binary-sbom.py``). Tag-49 PR #318 added the daily
SBOM-vs-baseline verifier. Tag-50 PR #323 added the end-to-end
baseline-refresh CLI.

What is still missing is the *build-reproducibility* axis: do two
independent invocations of the build-graph derivation produce
byte-equal output? An accidental dict-ordering bug, a timestamp
leak into a hash, or an environment-variable leak into the
fingerprint would silently break supply-chain provenance — the
generator would still produce SBOMs, but two operators running
the same source tree on the same Cargo.lock would get distinct
byte-streams. That is the failure-mode this Tag-51 substrate
defends against.

This script computes a deterministic "build-fingerprint" for each
of the 15 binaries from ``Cargo.lock`` + the canonical inventory.
The fingerprint is a SHA-256 over the canonical-form serialization
of the transitive-closure dependency set. The script then runs the
derivation *twice* in a single invocation and asserts byte-equal
output across both runs. If any binary's fingerprint differs, the
script fails RED and emits a Mira-Notify-shaped payload describing
the non-deterministic binary.

Sandbox posture
---------------

Strict hermetic: stdlib + tomllib only. No podman / cargo / cosign
/ network egress. The script parses ``Cargo.lock`` deterministically
and computes fingerprints in-process. The two-pass byte-equality
check is the entire substance of the audit.

This script does NOT invoke ``cargo build``. The "build" axis it
covers is the *derivation* of the build-fingerprint, not the
compile step. The compile-step axis is covered by Reza's
``cargo build --frozen`` CI gate and Tomás' Cosign-Policy
attestation chain. This script fills the gap between those two:
the fingerprint that the Cosign-Policy attestation chain anchors
must itself be deterministic.

Output surface
--------------

  * ``--out-json`` -- aggregate verdict JSON envelope, schema
    ``wakir-runtime/build-reproducibility-verdict@1``.
  * ``--out-textfile`` -- Prometheus textfile with per-binary
    determinism gauge (1.0 = deterministic, 0.0 = drift).
  * ``--out-markdown`` -- Job-Summary Markdown block.
  * ``--out-mira-notify`` -- Mira-Notify event JSON if any binary
    is non-deterministic (empty file if all GREEN).

Exit codes
----------

  * 0 -- all 15 binaries GREEN (deterministic).
  * 1 -- argument / input error.
  * 2 -- one or more binaries RED (non-deterministic). The Mira-
    Notify payload is written and the workflow surfaces the
    failure via Job-Summary.

Author: Kai Hoffmann (Dev-Engineering-3)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)


# ---------------------------------------------------------------------------
# Constants -- mirror the Tag-48 generator inventory byte-for-byte.
# ---------------------------------------------------------------------------

#: Canonical inventory order -- must match
#: ``scripts/observability/generate-15-binary-sbom.py``
#: ``TAG45_BINARY_INVENTORY`` byte-for-byte. The fingerprint is
#: parameterised by this list so a drift here would itself surface
#: as a fingerprint-shape change.
TAG45_BINARY_INVENTORY: Tuple[str, ...] = (
    "recovery",
    "state-backing",
    "fsm",
    "v907-verify",
    "bridge-diff",
    "subscribe-loop",
    "anchor-emitter",
    "svid-workload-identity",
    "bridge-audit-writer",
    "state-backing-welle4",
    "fsm-welle5",
    "subscribe-loop-welle6",
    "recovery-welle7",
    "bridge-audit-replay",
    "migrate-version",
)

#: Mapping of policy-name -> source crate-name. Mirrored from the
#: Tag-48 generator so the Tag-51 fingerprint is parameterised by
#: the exact same root-crate mapping.
POLICY_NAME_TO_CRATE: Mapping[str, str] = {
    "recovery": "persona-engine-recovery",
    "state-backing": "persona-engine-state-backing",
    "fsm": "persona-engine-fsm",
    "v907-verify": "persona-engine-v907-verify",
    "bridge-diff": "persona-engine-bridge-diff",
    "subscribe-loop": "persona-engine-subscribe-loop",
    "anchor-emitter": "persona-engine-anchor-emitter",
    "svid-workload-identity": "persona-engine-svid-workload-identity",
    "bridge-audit-writer": "persona-engine-bridge-audit-writer",
    "state-backing-welle4": "persona-engine-state-backing",
    "fsm-welle5": "persona-engine-fsm",
    "subscribe-loop-welle6": "persona-engine-subscribe-loop",
    "recovery-welle7": "persona-engine-recovery",
    "bridge-audit-replay": "persona-engine-bridge-audit-replay",
    "migrate-version": "persona-engine-migrate-version",
}

#: Fingerprint schema version anchor.
FINGERPRINT_SCHEMA_VERSION: str = "1"

#: Aggregate envelope schema name.
ENVELOPE_SCHEMA: str = "wakir-runtime/build-reproducibility-verdict@1"

#: Tool anchor for output envelopes.
TOOL_NAME: str = "wakir-runtime-build-reproducibility"
TOOL_VERSION: str = "tag-51"


# ---------------------------------------------------------------------------
# Dataclasses -- pure, immutable.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CratePackage:
    """A single package entry as parsed from Cargo.lock."""

    name: str
    version: str
    source: Optional[str] = None
    checksum: Optional[str] = None
    dependencies: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BinaryFingerprint:
    """The deterministic build-fingerprint for one binary."""

    binary_name: str
    root_crate: str
    transitive_count: int
    fingerprint_sha256: str


@dataclass(frozen=True)
class PassResult:
    """A single derivation pass over the full 15-binary inventory."""

    cargo_lock_sha256: str
    per_binary: Tuple[BinaryFingerprint, ...]


@dataclass(frozen=True)
class BinaryVerdict:
    """Per-binary determinism verdict across two passes."""

    binary_name: str
    deterministic: bool
    pass1_fingerprint: str
    pass2_fingerprint: str


@dataclass(frozen=True)
class AuditVerdict:
    """The aggregate verdict over the full 15-binary inventory."""

    cargo_lock_sha256: str
    deterministic_count: int
    drift_count: int
    per_binary: Tuple[BinaryVerdict, ...]
    overall_green: bool


# ---------------------------------------------------------------------------
# Pure functions: Cargo.lock parsing.
# ---------------------------------------------------------------------------


def parse_cargo_lock(
    cargo_lock_bytes: bytes,
) -> Tuple[CratePackage, ...]:
    """Parse the raw bytes of a Cargo.lock file deterministically.

    Mirrors the Tag-48 generator's parser invariants exactly: same
    handling of the ``"name version (source)"`` dependency-string
    form, same alphabetical sort preservation, same TOML loader.

    Args:
        cargo_lock_bytes: raw bytes of ``Cargo.lock``.

    Returns:
        A tuple of CratePackage entries in declaration order.

    Raises:
        ValueError if the TOML is missing the ``[[package]]`` array.
    """
    parsed = tomllib.loads(cargo_lock_bytes.decode("utf-8"))
    packages = parsed.get("package")
    if not packages:
        raise ValueError("Cargo.lock missing [[package]] array")

    out: List[CratePackage] = []
    for entry in packages:
        deps_raw = entry.get("dependencies", []) or []
        deps: List[str] = []
        for raw in deps_raw:
            dep_name = raw.split(" ", 1)[0]
            deps.append(dep_name)
        out.append(
            CratePackage(
                name=entry["name"],
                version=entry["version"],
                source=entry.get("source"),
                checksum=entry.get("checksum"),
                dependencies=tuple(deps),
            )
        )
    return tuple(out)


def build_package_index(
    packages: Sequence[CratePackage],
) -> Mapping[str, Tuple[CratePackage, ...]]:
    """Build a name -> tuple-of-versions lookup table.

    Multiple versions of the same package may co-exist in
    ``Cargo.lock`` (e.g. a transitive-dep pins v0.4 while a direct
    pin chooses v0.5). The index returns all versions so the
    closure walker can include every Cargo-linked variant.

    This mirrors the Tag-48 generator's ``index_packages_by_name``
    semantics exactly, so the Tag-51 fingerprint enumerates the
    same package set the SBOM generator does.
    """
    out: Dict[str, List[CratePackage]] = {}
    for pkg in packages:
        out.setdefault(pkg.name, []).append(pkg)
    return {k: tuple(v) for k, v in out.items()}


def transitive_closure(
    root_name: str,
    pkg_index: Mapping[str, Tuple[CratePackage, ...]],
) -> Tuple[CratePackage, ...]:
    """Compute the closed transitive dependency set from a root.

    Iterative BFS so recursion depth cannot blow the stack on
    deep dependency graphs. Visits each distinct ``(name, version)``
    pair once so Cargo's multi-version-per-name reality is captured.
    The output is sorted lexicographically by ``(name, version)``
    so the fingerprint is order-stable. Optional / target-conditional
    dependencies that Cargo did not resolve are skipped silently
    (consistent with the Tag-48 generator's behavior).

    Args:
        root_name: the workspace-local crate name to start from.
        pkg_index: the name -> tuple-of-versions lookup.

    Returns:
        A tuple of CratePackage entries (root + every reachable
        ``(name, version)``), sorted by ``(name, version)``.

    Raises:
        KeyError if the root_name is missing from pkg_index.
    """
    if root_name not in pkg_index:
        raise KeyError(f"Root crate not in Cargo.lock: {root_name}")

    visited: Dict[Tuple[str, str], CratePackage] = {}
    frontier: List[CratePackage] = list(pkg_index[root_name])
    while frontier:
        # Sort siblings deterministically before expansion.
        frontier.sort(key=lambda p: (p.name, p.version))
        next_frontier: List[CratePackage] = []
        for pkg in frontier:
            key = (pkg.name, pkg.version)
            if key in visited:
                continue
            visited[key] = pkg
            for dep_name in pkg.dependencies:
                if dep_name not in pkg_index:
                    # Optional / target-conditional dep that Cargo
                    # did not resolve into the lock-file. Skip
                    # silently; the Tag-48 generator does the same.
                    continue
                for candidate in pkg_index[dep_name]:
                    cand_key = (candidate.name, candidate.version)
                    if cand_key in visited:
                        continue
                    next_frontier.append(candidate)
        frontier = next_frontier

    return tuple(
        sorted(visited.values(), key=lambda p: (p.name, p.version))
    )


# ---------------------------------------------------------------------------
# Pure functions: fingerprint derivation.
# ---------------------------------------------------------------------------


def canonical_package_line(pkg: CratePackage) -> str:
    """Serialize one package to its canonical-form fingerprint line.

    The line format is deterministic and stable across Python
    versions because it uses fixed-string concatenation, no dict
    ordering, no f-string side-effects from locale, and no
    timestamp injection. Dependency edges are sorted before
    serialization so dependency-declaration-order in Cargo.lock
    does not leak into the fingerprint.

    Format::

        <name>|<version>|<source-or-empty>|<checksum-or-empty>|<deps-csv>

    where ``<deps-csv>`` is the comma-separated, lexicographically-
    sorted dependency-name list.
    """
    deps_sorted = ",".join(sorted(pkg.dependencies))
    source = pkg.source or ""
    checksum = pkg.checksum or ""
    return (
        f"{pkg.name}|{pkg.version}|{source}|{checksum}|{deps_sorted}"
    )


def fingerprint_binary(
    binary_name: str,
    pkg_index: Mapping[str, CratePackage],
) -> BinaryFingerprint:
    """Compute the deterministic fingerprint for one binary."""
    if binary_name not in POLICY_NAME_TO_CRATE:
        raise KeyError(
            f"Unknown binary in inventory: {binary_name}"
        )
    root_crate = POLICY_NAME_TO_CRATE[binary_name]
    closure = transitive_closure(root_crate, pkg_index)

    hasher = hashlib.sha256()
    # Schema-version prefix so any future change to the line
    # format forces a fingerprint rotation.
    hasher.update(
        f"build-reproducibility/v{FINGERPRINT_SCHEMA_VERSION}\n"
        .encode("utf-8")
    )
    # Bind the binary identity into the hash so two binaries with
    # identical transitive sets (e.g. welle-pinned variants of the
    # same root crate) still get distinct fingerprints if their
    # binary_name differs. This is a defensive choice: a future
    # change to POLICY_NAME_TO_CRATE that introduces a new
    # variant must visibly rotate the fingerprint.
    hasher.update(f"binary:{binary_name}\n".encode("utf-8"))
    hasher.update(f"root:{root_crate}\n".encode("utf-8"))
    for pkg in closure:
        hasher.update(canonical_package_line(pkg).encode("utf-8"))
        hasher.update(b"\n")
    digest = hasher.hexdigest()
    return BinaryFingerprint(
        binary_name=binary_name,
        root_crate=root_crate,
        transitive_count=len(closure),
        fingerprint_sha256=digest,
    )


def derive_pass(
    cargo_lock_bytes: bytes,
) -> PassResult:
    """Run one full derivation pass over the 15-binary inventory."""
    packages = parse_cargo_lock(cargo_lock_bytes)
    pkg_index = build_package_index(packages)
    cargo_lock_sha256 = hashlib.sha256(cargo_lock_bytes).hexdigest()
    fingerprints = tuple(
        fingerprint_binary(name, pkg_index)
        for name in TAG45_BINARY_INVENTORY
    )
    return PassResult(
        cargo_lock_sha256=cargo_lock_sha256,
        per_binary=fingerprints,
    )


def compare_passes(
    pass1: PassResult,
    pass2: PassResult,
) -> AuditVerdict:
    """Compare two derivation passes for byte-equal fingerprints."""
    if pass1.cargo_lock_sha256 != pass2.cargo_lock_sha256:
        raise ValueError(
            "Cargo.lock SHA differs across passes; inputs not "
            "stable."
        )
    if len(pass1.per_binary) != len(pass2.per_binary):
        raise ValueError(
            "Pass-1 and Pass-2 binary counts differ -- inventory "
            "drifted mid-run."
        )
    verdicts: List[BinaryVerdict] = []
    drift = 0
    for fp1, fp2 in zip(pass1.per_binary, pass2.per_binary):
        if fp1.binary_name != fp2.binary_name:
            raise ValueError(
                "Pass-1 and Pass-2 inventory order differs "
                f"({fp1.binary_name} vs {fp2.binary_name})."
            )
        deterministic = (
            fp1.fingerprint_sha256 == fp2.fingerprint_sha256
        )
        if not deterministic:
            drift += 1
        verdicts.append(
            BinaryVerdict(
                binary_name=fp1.binary_name,
                deterministic=deterministic,
                pass1_fingerprint=fp1.fingerprint_sha256,
                pass2_fingerprint=fp2.fingerprint_sha256,
            )
        )
    return AuditVerdict(
        cargo_lock_sha256=pass1.cargo_lock_sha256,
        deterministic_count=len(verdicts) - drift,
        drift_count=drift,
        per_binary=tuple(verdicts),
        overall_green=(drift == 0),
    )


# ---------------------------------------------------------------------------
# Rendering: JSON envelope, Prometheus textfile, Markdown.
# ---------------------------------------------------------------------------


def render_envelope_json(
    verdict: AuditVerdict,
    audit_ts: float,
) -> str:
    """Render the aggregate verdict as canonical JSON."""
    body = {
        "$schema": ENVELOPE_SCHEMA,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "audit_ts": audit_ts,
        "cargo_lock_sha256": verdict.cargo_lock_sha256,
        "overall_green": verdict.overall_green,
        "deterministic_count": verdict.deterministic_count,
        "drift_count": verdict.drift_count,
        "per_binary": [
            {
                "binary_name": bv.binary_name,
                "deterministic": bv.deterministic,
                "pass1_fingerprint_sha256": bv.pass1_fingerprint,
                "pass2_fingerprint_sha256": bv.pass2_fingerprint,
            }
            for bv in verdict.per_binary
        ],
    }
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


def render_prom_textfile(verdict: AuditVerdict) -> str:
    """Render Prometheus textfile metrics for the verdict."""
    lines: List[str] = []
    lines.append(
        "# HELP wakir_build_reproducibility_deterministic "
        "1 if the binary's fingerprint is byte-equal across "
        "two derivation passes, 0 otherwise."
    )
    lines.append(
        "# TYPE wakir_build_reproducibility_deterministic gauge"
    )
    for bv in verdict.per_binary:
        value = "1" if bv.deterministic else "0"
        lines.append(
            "wakir_build_reproducibility_deterministic"
            f'{{binary="{bv.binary_name}"}} {value}'
        )
    lines.append(
        "# HELP wakir_build_reproducibility_drift_count "
        "Number of binaries with non-deterministic fingerprints."
    )
    lines.append(
        "# TYPE wakir_build_reproducibility_drift_count gauge"
    )
    lines.append(
        "wakir_build_reproducibility_drift_count "
        f"{verdict.drift_count}"
    )
    return "\n".join(lines) + "\n"


def render_markdown(verdict: AuditVerdict) -> str:
    """Render Job-Summary Markdown."""
    overall = "GREEN" if verdict.overall_green else "RED"
    lines: List[str] = []
    lines.append("## 15-Binary Build-Reproducibility Audit")
    lines.append("")
    lines.append(f"**Overall**: `{overall}`")
    lines.append(
        f"**Cargo.lock SHA-256**: `{verdict.cargo_lock_sha256}`"
    )
    lines.append(
        f"**Deterministic**: "
        f"{verdict.deterministic_count} / "
        f"{len(verdict.per_binary)}"
    )
    lines.append(
        f"**Drift**: {verdict.drift_count}"
    )
    lines.append("")
    lines.append(
        "| Binary | Deterministic | Pass-1 SHA (prefix) | "
        "Pass-2 SHA (prefix) |"
    )
    lines.append(
        "|---|---|---|---|"
    )
    for bv in verdict.per_binary:
        mark = "OK" if bv.deterministic else "DRIFT"
        p1 = bv.pass1_fingerprint[:12]
        p2 = bv.pass2_fingerprint[:12]
        lines.append(
            f"| `{bv.binary_name}` | {mark} | `{p1}` | `{p2}` |"
        )
    return "\n".join(lines) + "\n"


def render_mira_notify(
    verdict: AuditVerdict,
    audit_ts: float,
) -> str:
    """Render a Mira-Notify event JSON for the drift binaries.

    Returns an empty string if the audit is GREEN (no event emitted).
    """
    if verdict.overall_green:
        return ""
    drift_binaries = [
        bv.binary_name for bv in verdict.per_binary
        if not bv.deterministic
    ]
    body = {
        "$schema": "wakir-runtime/mira-notify-event@1",
        "event_type": "build-reproducibility-drift",
        "severity": "RED",
        "audit_ts": audit_ts,
        "cargo_lock_sha256": verdict.cargo_lock_sha256,
        "drift_count": verdict.drift_count,
        "drift_binaries": drift_binaries,
        "summary": (
            f"{verdict.drift_count}/{len(verdict.per_binary)} "
            "binaries produced non-deterministic build "
            "fingerprints across two derivation passes. "
            "Supply-chain provenance is compromised until root "
            "cause is identified."
        ),
    }
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# IO helpers.
# ---------------------------------------------------------------------------


def write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def read_cargo_lock(path: Path) -> bytes:
    if not path.is_file():
        raise FileNotFoundError(
            f"Cargo.lock not found at: {path}"
        )
    return path.read_bytes()


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the 15-binary build-fingerprint "
            "derivation is byte-equal across two independent "
            "passes over Cargo.lock. Tag-51 Kai."
        )
    )
    parser.add_argument(
        "--cargo-lock",
        required=True,
        type=Path,
        help="Path to the workspace Cargo.lock to audit.",
    )
    parser.add_argument(
        "--out-json",
        required=False,
        type=Path,
        default=None,
        help="Aggregate verdict JSON envelope output path.",
    )
    parser.add_argument(
        "--out-textfile",
        required=False,
        type=Path,
        default=None,
        help="Prometheus textfile metrics output path.",
    )
    parser.add_argument(
        "--out-markdown",
        required=False,
        type=Path,
        default=None,
        help="Job-Summary Markdown output path.",
    )
    parser.add_argument(
        "--out-mira-notify",
        required=False,
        type=Path,
        default=None,
        help=(
            "Mira-Notify event JSON output path. Written only if "
            "any binary is non-deterministic; otherwise the file "
            "is created empty (zero bytes) as a probe-ran marker."
        ),
    )
    parser.add_argument(
        "--audit-ts",
        required=False,
        type=float,
        default=None,
        help=(
            "Override the audit-timestamp (float seconds since "
            "epoch). Default reads SOURCE_DATE_EPOCH if set, else "
            "uses 0.0 (deterministic-mode for hermetic tests)."
        ),
    )
    return parser.parse_args(argv)


def _resolve_audit_ts(arg_value: Optional[float]) -> float:
    """Resolve the audit timestamp deterministically.

    Precedence:
      1. ``--audit-ts`` if supplied.
      2. ``SOURCE_DATE_EPOCH`` env-var if set (reproducible-build
         convention).
      3. ``0.0`` (hermetic-default; the audit envelope is meant to
         be byte-stable across runs, not human-readable).
    """
    if arg_value is not None:
        return arg_value
    sde = os.environ.get("SOURCE_DATE_EPOCH")
    if sde:
        try:
            return float(sde)
        except ValueError as exc:
            raise ValueError(
                f"SOURCE_DATE_EPOCH not a float: {sde!r}"
            ) from exc
    return 0.0


def run_audit(
    cargo_lock_bytes: bytes,
) -> AuditVerdict:
    """Run two independent derivation passes and compare."""
    pass1 = derive_pass(cargo_lock_bytes)
    pass2 = derive_pass(cargo_lock_bytes)
    return compare_passes(pass1, pass2)


def main(argv: Sequence[str]) -> int:
    args = _parse_args(argv)
    try:
        cargo_lock_bytes = read_cargo_lock(args.cargo_lock)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        audit_ts = _resolve_audit_ts(args.audit_ts)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        verdict = run_audit(cargo_lock_bytes)
    except (ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.out_json is not None:
        write_text(
            args.out_json,
            render_envelope_json(verdict, audit_ts),
        )
    if args.out_textfile is not None:
        write_text(
            args.out_textfile,
            render_prom_textfile(verdict),
        )
    if args.out_markdown is not None:
        write_text(
            args.out_markdown,
            render_markdown(verdict),
        )
    if args.out_mira_notify is not None:
        notify_body = render_mira_notify(verdict, audit_ts)
        write_text(args.out_mira_notify, notify_body)

    if not verdict.overall_green:
        print(
            f"RED: {verdict.drift_count}/"
            f"{len(verdict.per_binary)} binaries non-deterministic.",
            file=sys.stderr,
        )
        return 2

    print(
        f"GREEN: {verdict.deterministic_count}/"
        f"{len(verdict.per_binary)} binaries deterministic."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
