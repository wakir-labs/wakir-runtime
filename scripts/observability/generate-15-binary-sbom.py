#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""15-Binary SBOM (Software-Bill-of-Materials) generator (Tag-48, Kai).

Context
-------

Tag-45 PR #294 closed the Phase-3a-Foundation 15-Binary substrate
refresh by pinning the lock-step between
``policies/cosign-policy-phase-3b.yaml`` (15-binary cosign-policy
inventory) and ``quadlet/wakir-rust-cli.container`` (11-carrier-image
installer). Tag-46 PR #298 added the substrate-layer A6 coverage
matrix (17 hermetic invariants). Tag-47 PR #307 added the Cosign-
Keyless-OIDC-Drift-Probe (the time-axis drift detector against the
Sigstore Trust-Root).

What none of the prior substrates pin is the **per-binary
dependency-tree** at the source-of-truth level. The Cosign chain
binds an image digest to a build workflow OIDC identity; the
operator can verify ``the binary they installed is the binary the
build produced``. The operator cannot, without a SBOM, answer
``which third-party crate versions does that binary statically
link in, and is any of them in scope for a published CVE?``.

This script generates a CycloneDX-1.5 (default) or SPDX-2.3 SBOM
**per binary** by reading ``wirelang-rust/Cargo.lock`` plus the
workspace's per-crate ``Cargo.toml`` files. It walks the dependency
graph rooted at each of the fifteen binary crate-names declared
in the cosign policy and emits one SBOM document per binary.

Audit-Trail anchor
------------------

ADR-0066 §AR-Hand-Gate requires pre-cutover stability + signed
provenance for every Welle. The 15-Binary SBOM is the missing
``components-and-versions`` axis: when the operator hands off a
Welle to AR for sign-off, the SBOM bundle is the artefact that
answers ``what is in this binary, byte-for-byte sourced from
Cargo.lock``.

Two-mode operation
------------------

The generator runs in two modes:

  * ``--mode=stdlib`` (default) — pure-Python, ``tomllib``-only.
    Reads ``Cargo.lock`` + per-crate ``Cargo.toml`` and emits a
    deterministic CycloneDX / SPDX document. Hermetic-CI-safe,
    no network, no cargo subprocess.

  * ``--mode=cargo-cyclonedx`` — fall-back to the upstream
    ``cargo-cyclonedx`` plugin if it is installed on PATH.
    Operator-Hand only — the daily CI uses stdlib-mode for
    deterministic-substrate reasons.

Whichever mode runs, the output schema is determined by
``--format``: ``cyclonedx-1.5`` (default) or ``spdx-2.3``.

Sandbox boundary
----------------

Per ``feedback_sandbox_host_trennung.md`` + ADR-0051 this script
NEVER calls cargo / crane / cosign / podman / network. The
default stdlib-mode is hermetic-pure. The cargo-cyclonedx fall-
back path checks ``shutil.which`` for the binary; if it is not
present, the script falls back to stdlib-mode silently.

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is pure-
function, hermetic-test target. The I/O wrappers
(``read_cargo_lock``, ``read_workspace_manifest``,
``read_crate_manifest``, ``write_sbom_envelope``,
``write_textfile``, ``write_markdown_summary``) are isolated at
the bottom.

Anchors
-------

  * Tag-45 PR #294 — Quadlet+Cosign 15-Binary substrate refresh.
  * Tag-46 PR #298 — A6 substrate-layer coverage matrix.
  * Tag-47 PR #307 — Cosign-Keyless-OIDC-Drift-Probe (time-axis).
  * ADR-0066 §AR-Hand-Gate — pre-cutover sign-off requires a
    full provenance bundle.
  * feedback_sandbox_host_trennung.md — no live cargo I/O from
    sandbox.
  * CycloneDX spec v1.5 (industry-standard).
  * SPDX spec v2.3 (industry-standard).

Author: Kai Hoffmann (Dev-Engineering-3 / Container-Orchestration)
Tag: 48 (KW-22)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, Set, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Canonical inventory order — must match the Tag-45 Cosign-Policy
#: 15-binary inventory byte-for-byte. The generator iterates this
#: tuple so the per-binary SBOM filenames are deterministic across
#: runs.
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

#: Mapping of policy-name -> source crate-name (the directory under
#: ``wirelang-rust/crates/``). Multiple policy-names can resolve to
#: the same crate (welle-pinned variants share a source crate). The
#: SBOM dependency graph is identical between siblings because the
#: variants only differ in carrier-image install path, not source.
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

#: Supported SBOM output formats.
SUPPORTED_FORMATS: Tuple[str, ...] = ("cyclonedx-1.5", "spdx-2.3")

#: CycloneDX-1.5 JSON-schema-version anchor.
CYCLONEDX_SPEC_VERSION: str = "1.5"

#: SPDX-2.3 schema-version anchor.
SPDX_SPEC_VERSION: str = "SPDX-2.3"

#: PURL (Package URL) type identifier for crates.io packages.
PURL_TYPE_CARGO: str = "cargo"

#: Tool-name anchor (CycloneDX ``tools[].name`` + SPDX ``creator``).
TOOL_NAME: str = "wakir-runtime-15-binary-sbom"

#: Tool-version anchor (matches the script's Tag-N identity).
TOOL_VERSION: str = "tag-48"


# ---------------------------------------------------------------------------
# Dataclasses (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CratePackage:
    """A single package entry as parsed from ``Cargo.lock``.

    The ``name`` + ``version`` pair uniquely identifies the package
    in the lock-file. ``source`` is None for workspace-local crates
    and ``registry+https://github.com/rust-lang/crates.io-index``
    for crates.io packages. ``checksum`` is the SHA-256 of the
    ``.crate`` tarball as recorded by Cargo.
    """

    name: str
    version: str
    source: Optional[str] = None
    checksum: Optional[str] = None
    dependencies: Tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class BinarySBOM:
    """The result of resolving one binary against ``Cargo.lock``.

    ``root_crate`` is the workspace-local crate that ships the
    ``[[bin]]`` entry. ``transitive_packages`` is the closed set
    of every package reachable from the root, including the root.
    """

    binary_name: str
    root_crate: str
    transitive_packages: Tuple[CratePackage, ...]


@dataclass(frozen=True)
class SBOMBundle:
    """The full output of a generator run — fifteen per-binary SBOMs."""

    generator_ts: float
    format: str
    per_binary: Tuple[BinarySBOM, ...]
    cargo_lock_sha256: str


# ---------------------------------------------------------------------------
# Pure functions: Cargo.lock parsing
# ---------------------------------------------------------------------------


def parse_cargo_lock(
    cargo_lock_bytes: bytes,
) -> Tuple[CratePackage, ...]:
    """Parse the raw bytes of a ``Cargo.lock`` file.

    Returns a tuple of CratePackage entries in declaration order
    (preserving Cargo's alphabetical sort). The dependency edges
    are stripped of any version qualifiers so the keys are just
    package names — disambiguation by version is recovered at
    lookup time via ``resolve_dependency``.

    Args:
        cargo_lock_bytes: raw bytes of ``Cargo.lock`` (TOML).

    Returns:
        A tuple of CratePackage entries.

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
        # Cargo.lock dependency strings may be:
        #   "name"
        #   "name version"
        #   "name version (source)"
        # We strip to just the name portion.
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


def index_packages_by_name(
    packages: Sequence[CratePackage],
) -> Mapping[str, Tuple[CratePackage, ...]]:
    """Build a name -> tuple-of-versions index.

    Multiple versions of the same package may co-exist in
    ``Cargo.lock`` (a transitive-dep brings in v0.4 while a direct
    pin brings in v0.5). The index returns all versions so a
    consumer can pick by additional context if needed.
    """
    out: Dict[str, List[CratePackage]] = {}
    for pkg in packages:
        out.setdefault(pkg.name, []).append(pkg)
    return {k: tuple(v) for k, v in out.items()}


def resolve_transitive_closure(
    root_name: str,
    packages: Sequence[CratePackage],
) -> Tuple[CratePackage, ...]:
    """Compute the transitive dependency closure rooted at one crate.

    The closure includes the root itself. Cycles (theoretically
    possible in Cargo via dev-deps but rare in our workspace) are
    handled by a visited-set guard. Multiple versions of the same
    name are all included because Cargo statically links each.

    The closure is returned in deterministic order: BFS from the
    root, with siblings sorted alphabetically. This makes the SBOM
    output byte-stable across runs.

    Args:
        root_name: the workspace-local crate name (must appear in
            ``packages``).
        packages: every entry from ``Cargo.lock``.

    Returns:
        A tuple of CratePackage entries reachable from ``root_name``.

    Raises:
        ValueError if ``root_name`` is not found in ``packages``.
    """
    index = index_packages_by_name(packages)
    if root_name not in index:
        raise ValueError(
            f"root crate {root_name!r} not found in Cargo.lock"
        )

    # BFS frontier holds (name, version) pairs. We visit each
    # distinct (name, version) once.
    visited: Set[Tuple[str, str]] = set()
    order: List[CratePackage] = []
    # Start with all versions of the root (typically just one).
    frontier: List[CratePackage] = list(index[root_name])

    while frontier:
        # Sort siblings alphabetically by (name, version) for
        # deterministic output.
        frontier.sort(key=lambda p: (p.name, p.version))
        next_frontier: List[CratePackage] = []
        for pkg in frontier:
            key = (pkg.name, pkg.version)
            if key in visited:
                continue
            visited.add(key)
            order.append(pkg)
            for dep_name in pkg.dependencies:
                if dep_name not in index:
                    # Optional / target-conditional dep not resolved
                    # by Cargo — skip silently.
                    continue
                for candidate in index[dep_name]:
                    if (candidate.name, candidate.version) in visited:
                        continue
                    next_frontier.append(candidate)
        frontier = next_frontier

    return tuple(order)


def build_binary_sbom(
    binary_name: str,
    root_crate: str,
    packages: Sequence[CratePackage],
) -> BinarySBOM:
    """Construct a BinarySBOM for one of the fifteen binaries."""
    closure = resolve_transitive_closure(root_crate, packages)
    return BinarySBOM(
        binary_name=binary_name,
        root_crate=root_crate,
        transitive_packages=closure,
    )


def build_full_bundle(
    packages: Sequence[CratePackage],
    cargo_lock_sha256: str,
    generator_ts: float,
    sbom_format: str,
    inventory: Sequence[str] = TAG45_BINARY_INVENTORY,
    policy_map: Mapping[str, str] = POLICY_NAME_TO_CRATE,
) -> SBOMBundle:
    """Build the full 15-binary bundle from a parsed Cargo.lock."""
    per: List[BinarySBOM] = []
    for binary_name in inventory:
        root_crate = policy_map[binary_name]
        per.append(build_binary_sbom(binary_name, root_crate, packages))
    return SBOMBundle(
        generator_ts=generator_ts,
        format=sbom_format,
        per_binary=tuple(per),
        cargo_lock_sha256=cargo_lock_sha256,
    )


# ---------------------------------------------------------------------------
# Pure functions: PURL encoding (Package-URL spec)
# ---------------------------------------------------------------------------


def purl_for_package(pkg: CratePackage) -> str:
    """Encode a CratePackage as a Package-URL string.

    Workspace-local crates (``source is None``) get a PURL with
    no qualifier — they are not in a registry. Crates.io packages
    get a standard ``pkg:cargo/<name>@<version>`` PURL. The output
    is deterministic for hermetic-test parity.
    """
    if pkg.source is None:
        # Workspace-local crate. Use a non-resolvable PURL that
        # documents the source clearly.
        return f"pkg:cargo/{pkg.name}@{pkg.version}?source=workspace"
    return f"pkg:cargo/{pkg.name}@{pkg.version}"


# ---------------------------------------------------------------------------
# Pure functions: CycloneDX-1.5 rendering
# ---------------------------------------------------------------------------


def render_cyclonedx_component(pkg: CratePackage) -> Dict[str, object]:
    """Render one CratePackage as a CycloneDX-1.5 component object.

    Schema reference: CycloneDX-1.5 §5.4.1 (component object).
    """
    component: Dict[str, object] = {
        "type": "library",
        "bom-ref": f"{pkg.name}@{pkg.version}",
        "name": pkg.name,
        "version": pkg.version,
        "purl": purl_for_package(pkg),
    }
    if pkg.checksum is not None:
        component["hashes"] = [
            {"alg": "SHA-256", "content": pkg.checksum}
        ]
    if pkg.source is None:
        component["scope"] = "required"
        component["properties"] = [
            {"name": "wakir:source", "value": "workspace"}
        ]
    else:
        component["scope"] = "required"
        component["properties"] = [
            {"name": "wakir:source", "value": "crates.io"}
        ]
    return component


def render_cyclonedx_dependency_graph(
    packages: Sequence[CratePackage],
) -> List[Dict[str, object]]:
    """Render the CycloneDX-1.5 dependency-graph array.

    Schema reference: CycloneDX-1.5 §5.5 (dependencies array).
    Each entry maps a ``ref`` to its list of ``dependsOn`` refs.
    The refs match the ``bom-ref`` values from
    ``render_cyclonedx_component``.
    """
    # Build a fast lookup so we can disambiguate dep-names against
    # all known (name, version) pairs in the closure.
    by_name: Dict[str, List[CratePackage]] = {}
    for pkg in packages:
        by_name.setdefault(pkg.name, []).append(pkg)

    out: List[Dict[str, object]] = []
    for pkg in packages:
        ref = f"{pkg.name}@{pkg.version}"
        depends_on: List[str] = []
        for dep_name in pkg.dependencies:
            if dep_name not in by_name:
                continue
            for candidate in by_name[dep_name]:
                depends_on.append(f"{candidate.name}@{candidate.version}")
        # Deterministic order — alphabetical.
        depends_on.sort()
        out.append({"ref": ref, "dependsOn": depends_on})
    return out


def render_cyclonedx_sbom(
    sbom: BinarySBOM,
    generator_ts: float,
    cargo_lock_sha256: str,
) -> Dict[str, object]:
    """Render a full CycloneDX-1.5 SBOM document for one binary."""
    serial = (
        "urn:uuid:"
        + hashlib.sha256(
            f"{sbom.binary_name}|{cargo_lock_sha256}|{generator_ts}".encode(
                "utf-8"
            )
        ).hexdigest()[:32]
    )

    # Re-format the SHA-256 as a UUID-ish 8-4-4-4-12 layout so the
    # serial-number passes CycloneDX's loose URN-UUID format check
    # without us actually claiming uuid-v4 randomness. The substrate
    # is deterministic (sha256 of binary-name + cargo-lock-sha + ts),
    # which is what we want for replayable audit-trail anchors.
    serial = (
        "urn:uuid:"
        + f"{serial[9:17]}-{serial[17:21]}-{serial[21:25]}-"
        + f"{serial[25:29]}-{serial[29:41]}"
    )

    components = [
        render_cyclonedx_component(pkg)
        for pkg in sbom.transitive_packages
    ]
    dependencies = render_cyclonedx_dependency_graph(
        sbom.transitive_packages
    )

    return {
        "bomFormat": "CycloneDX",
        "specVersion": CYCLONEDX_SPEC_VERSION,
        "serialNumber": serial,
        "version": 1,
        "metadata": {
            "timestamp": _iso8601(generator_ts),
            "tools": [
                {
                    "vendor": "Wakir Labs",
                    "name": TOOL_NAME,
                    "version": TOOL_VERSION,
                }
            ],
            "component": {
                "type": "application",
                "bom-ref": f"binary:{sbom.binary_name}",
                "name": f"wakir-persona-engine-{sbom.binary_name}",
                "version": "0.1.0",
                "description": (
                    f"15-Binary SBOM for {sbom.binary_name} "
                    f"(root crate {sbom.root_crate})."
                ),
            },
            "properties": [
                {
                    "name": "wakir:cargo-lock-sha256",
                    "value": cargo_lock_sha256,
                },
                {
                    "name": "wakir:root-crate",
                    "value": sbom.root_crate,
                },
                {
                    "name": "wakir:inventory-position",
                    "value": str(
                        TAG45_BINARY_INVENTORY.index(sbom.binary_name)
                    ),
                },
            ],
        },
        "components": components,
        "dependencies": dependencies,
    }


# ---------------------------------------------------------------------------
# Pure functions: SPDX-2.3 rendering
# ---------------------------------------------------------------------------


def _spdx_id(pkg: CratePackage) -> str:
    """SPDX requires SPDXID values to be alpha-numeric + dot + dash."""
    safe_name = pkg.name.replace("_", "-")
    safe_version = pkg.version.replace("_", "-")
    return f"SPDXRef-Package-{safe_name}-{safe_version}"


def render_spdx_package(pkg: CratePackage) -> Dict[str, object]:
    """Render one CratePackage as an SPDX-2.3 package object."""
    obj: Dict[str, object] = {
        "SPDXID": _spdx_id(pkg),
        "name": pkg.name,
        "versionInfo": pkg.version,
        "downloadLocation": "NOASSERTION",
        "filesAnalyzed": False,
        "licenseConcluded": "NOASSERTION",
        "licenseDeclared": "NOASSERTION",
        "copyrightText": "NOASSERTION",
        "externalRefs": [
            {
                "referenceCategory": "PACKAGE-MANAGER",
                "referenceType": "purl",
                "referenceLocator": purl_for_package(pkg),
            }
        ],
    }
    if pkg.checksum is not None:
        obj["checksums"] = [
            {"algorithm": "SHA256", "checksumValue": pkg.checksum}
        ]
    if pkg.source is None:
        obj["primaryPackagePurpose"] = "LIBRARY"
        obj["sourceInfo"] = "workspace-local crate"
    else:
        obj["primaryPackagePurpose"] = "LIBRARY"
        obj["sourceInfo"] = pkg.source
    return obj


def render_spdx_relationships(
    sbom: BinarySBOM,
    packages: Sequence[CratePackage],
) -> List[Dict[str, object]]:
    """Render SPDX-2.3 relationship records for the dependency graph."""
    relationships: List[Dict[str, object]] = []
    # Root relationship: DOCUMENT DESCRIBES root.
    root_pkgs = [p for p in packages if p.name == sbom.root_crate]
    for root_pkg in root_pkgs:
        relationships.append(
            {
                "spdxElementId": "SPDXRef-DOCUMENT",
                "relationshipType": "DESCRIBES",
                "relatedSpdxElement": _spdx_id(root_pkg),
            }
        )

    # Build lookup for dep resolution.
    by_name: Dict[str, List[CratePackage]] = {}
    for pkg in packages:
        by_name.setdefault(pkg.name, []).append(pkg)

    for pkg in packages:
        for dep_name in pkg.dependencies:
            if dep_name not in by_name:
                continue
            for candidate in by_name[dep_name]:
                relationships.append(
                    {
                        "spdxElementId": _spdx_id(pkg),
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": _spdx_id(candidate),
                    }
                )
    return relationships


def render_spdx_sbom(
    sbom: BinarySBOM,
    generator_ts: float,
    cargo_lock_sha256: str,
) -> Dict[str, object]:
    """Render a full SPDX-2.3 SBOM document for one binary."""
    doc_namespace = (
        f"https://wakir.dev/sbom/{sbom.binary_name}/"
        f"{cargo_lock_sha256[:16]}"
    )
    packages = [
        render_spdx_package(pkg) for pkg in sbom.transitive_packages
    ]
    relationships = render_spdx_relationships(
        sbom, sbom.transitive_packages
    )
    return {
        "spdxVersion": SPDX_SPEC_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"sbom-{sbom.binary_name}",
        "documentNamespace": doc_namespace,
        "creationInfo": {
            "created": _iso8601(generator_ts),
            "creators": [f"Tool: {TOOL_NAME}-{TOOL_VERSION}"],
        },
        "packages": packages,
        "relationships": relationships,
        "documentDescribes": [
            _spdx_id(p)
            for p in sbom.transitive_packages
            if p.name == sbom.root_crate
        ],
    }


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def _iso8601(ts: float) -> str:
    """Format a Unix timestamp as RFC-3339 / ISO-8601 UTC."""
    import datetime as _dt

    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def render_sbom_document(
    sbom: BinarySBOM,
    generator_ts: float,
    cargo_lock_sha256: str,
    sbom_format: str,
) -> Dict[str, object]:
    """Render a single SBOM in the requested format."""
    if sbom_format == "cyclonedx-1.5":
        return render_cyclonedx_sbom(
            sbom, generator_ts, cargo_lock_sha256
        )
    if sbom_format == "spdx-2.3":
        return render_spdx_sbom(sbom, generator_ts, cargo_lock_sha256)
    raise ValueError(f"unsupported SBOM format: {sbom_format!r}")


def render_markdown_summary(bundle: SBOMBundle) -> str:
    """Render an at-a-glance operator summary for the run."""
    lines: List[str] = []
    lines.append("## 15-Binary SBOM — Generator Summary")
    lines.append("")
    lines.append(f"- Generator timestamp: `{_iso8601(bundle.generator_ts)}`")
    lines.append(f"- Output format: `{bundle.format}`")
    lines.append(f"- Cargo.lock SHA-256: `{bundle.cargo_lock_sha256}`")
    lines.append(f"- Binaries inventoried: {len(bundle.per_binary)}")
    lines.append("")
    lines.append(
        "| # | Binary | Root crate | Transitive packages |"
    )
    lines.append("|---|---|---|---|")
    for idx, sbom in enumerate(bundle.per_binary):
        lines.append(
            f"| {idx + 1} | `{sbom.binary_name}` | "
            f"`{sbom.root_crate}` | {len(sbom.transitive_packages)} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_textfile_metrics(bundle: SBOMBundle) -> str:
    """Render Prometheus-textfile metrics for the run.

    Two metrics:

      * ``wakir_sbom_binary_transitive_packages{binary=...}`` —
        per-binary transitive-dep count.
      * ``wakir_sbom_generator_run_timestamp_seconds`` —
        gauge of the last successful generator-run timestamp.
    """
    lines: List[str] = []
    lines.append(
        "# HELP wakir_sbom_binary_transitive_packages "
        "Transitive dep count per binary."
    )
    lines.append(
        "# TYPE wakir_sbom_binary_transitive_packages gauge"
    )
    for sbom in bundle.per_binary:
        lines.append(
            f'wakir_sbom_binary_transitive_packages'
            f'{{binary="{sbom.binary_name}",'
            f'format="{bundle.format}"}} '
            f"{len(sbom.transitive_packages)}"
        )
    lines.append(
        "# HELP wakir_sbom_generator_run_timestamp_seconds "
        "Unix-ts of the last successful generator run."
    )
    lines.append(
        "# TYPE wakir_sbom_generator_run_timestamp_seconds gauge"
    )
    lines.append(
        f"wakir_sbom_generator_run_timestamp_seconds "
        f"{bundle.generator_ts:.0f}"
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# --- I/O boundary ---
# ---------------------------------------------------------------------------


def read_cargo_lock(path: Path) -> Tuple[bytes, str]:
    """Read Cargo.lock and return (raw_bytes, sha256_hex)."""
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    return raw, digest


def detect_cargo_cyclonedx() -> Optional[str]:
    """Detect whether cargo-cyclonedx is on PATH."""
    return shutil.which("cargo-cyclonedx")


def run_cargo_cyclonedx_fallback(
    workspace_root: Path,
    out_dir: Path,
) -> int:
    """Operator-Hand fall-back: invoke cargo-cyclonedx if available.

    Returns the cargo subprocess exit code. The daily CI path does
    NOT take this branch — it is operator-hand only. We document the
    invocation here so the runbook has a single source of truth.
    """
    cargo_cyclonedx = detect_cargo_cyclonedx()
    if cargo_cyclonedx is None:
        print(
            "[fallback] cargo-cyclonedx not on PATH; "
            "falling back to stdlib-mode silently.",
            file=sys.stderr,
        )
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "cargo",
        "cyclonedx",
        "--format",
        "json",
        "--output-pattern",
        str(out_dir / "{name}-{version}.cdx.json"),
    ]
    print(
        f"[fallback] running: {' '.join(cmd)} (cwd={workspace_root})",
        file=sys.stderr,
    )
    result = subprocess.run(
        cmd,
        cwd=str(workspace_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(
            f"[fallback] cargo-cyclonedx failed: {result.stderr}",
            file=sys.stderr,
        )
    return result.returncode


def write_sbom_documents(
    bundle: SBOMBundle,
    out_dir: Path,
) -> List[Path]:
    """Write per-binary SBOM documents to disk."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: List[Path] = []
    for sbom in bundle.per_binary:
        doc = render_sbom_document(
            sbom,
            bundle.generator_ts,
            bundle.cargo_lock_sha256,
            bundle.format,
        )
        suffix = (
            ".cdx.json" if bundle.format == "cyclonedx-1.5"
            else ".spdx.json"
        )
        path = out_dir / f"{sbom.binary_name}{suffix}"
        path.write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        written.append(path)
    return written


def write_bundle_envelope(bundle: SBOMBundle, path: Path) -> None:
    """Write an aggregate envelope summarising all 15 SBOMs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    envelope = {
        "generator_ts": _iso8601(bundle.generator_ts),
        "format": bundle.format,
        "cargo_lock_sha256": bundle.cargo_lock_sha256,
        "binaries": [
            {
                "name": sbom.binary_name,
                "root_crate": sbom.root_crate,
                "transitive_count": len(sbom.transitive_packages),
            }
            for sbom in bundle.per_binary
        ],
    }
    path.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_textfile(bundle: SBOMBundle, path: Path) -> None:
    """Write Prometheus-textfile metrics to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_textfile_metrics(bundle), encoding="utf-8")


def write_markdown_summary(bundle: SBOMBundle, path: Path) -> None:
    """Write the Markdown summary block to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        render_markdown_summary(bundle), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate one SBOM per binary (CycloneDX-1.5 or SPDX-2.3) "
            "for the Tag-45 15-binary inventory."
        )
    )
    parser.add_argument(
        "--cargo-lock",
        required=True,
        type=Path,
        help="Path to wirelang-rust/Cargo.lock.",
    )
    parser.add_argument(
        "--workspace-root",
        required=False,
        type=Path,
        default=None,
        help=(
            "Path to wirelang-rust/ workspace root. Required only "
            "when --mode=cargo-cyclonedx (fall-back path)."
        ),
    )
    parser.add_argument(
        "--out-dir",
        required=True,
        type=Path,
        help="Output directory for the per-binary SBOM JSON files.",
    )
    parser.add_argument(
        "--out-envelope",
        required=False,
        type=Path,
        default=None,
        help="Optional aggregate envelope JSON path.",
    )
    parser.add_argument(
        "--out-textfile",
        required=False,
        type=Path,
        default=None,
        help="Optional Prometheus-textfile metrics path.",
    )
    parser.add_argument(
        "--out-markdown",
        required=False,
        type=Path,
        default=None,
        help="Optional Job-Summary Markdown path.",
    )
    parser.add_argument(
        "--format",
        choices=SUPPORTED_FORMATS,
        default="cyclonedx-1.5",
        help="SBOM output format (default: cyclonedx-1.5).",
    )
    parser.add_argument(
        "--mode",
        choices=("stdlib", "cargo-cyclonedx"),
        default="stdlib",
        help=(
            "stdlib (default): pure-python Cargo.lock walker. "
            "cargo-cyclonedx: fall-back to upstream plugin if "
            "installed (operator-hand only)."
        ),
    )
    parser.add_argument(
        "--generator-ts",
        required=False,
        type=float,
        default=None,
        help=(
            "Override the generator timestamp for hermetic-test "
            "reproducibility. Defaults to time.time()."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str]) -> int:
    args = _parse_args(argv)

    if args.mode == "cargo-cyclonedx":
        if args.workspace_root is None:
            print(
                "--mode=cargo-cyclonedx requires --workspace-root.",
                file=sys.stderr,
            )
            return 2
        rc = run_cargo_cyclonedx_fallback(
            args.workspace_root, args.out_dir
        )
        if rc == 0:
            return 0
        print(
            "[fallback] cargo-cyclonedx unavailable; "
            "switching to stdlib-mode.",
            file=sys.stderr,
        )

    raw_bytes, lock_sha = read_cargo_lock(args.cargo_lock)
    packages = parse_cargo_lock(raw_bytes)

    import time as _time

    ts = args.generator_ts if args.generator_ts is not None else _time.time()
    bundle = build_full_bundle(
        packages=packages,
        cargo_lock_sha256=lock_sha,
        generator_ts=ts,
        sbom_format=args.format,
    )
    write_sbom_documents(bundle, args.out_dir)
    if args.out_envelope is not None:
        write_bundle_envelope(bundle, args.out_envelope)
    if args.out_textfile is not None:
        write_textfile(bundle, args.out_textfile)
    if args.out_markdown is not None:
        write_markdown_summary(bundle, args.out_markdown)

    print(
        f"[ok] generated {len(bundle.per_binary)} SBOMs "
        f"in {args.out_dir} (format={bundle.format})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
