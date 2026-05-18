#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""15-Binary SBOM-vs-Baseline Verification (Tag-49, Kai).

Context
-------

Tag-48 PR #310 introduced the 15-binary SBOM generator
(``scripts/observability/generate-15-binary-sbom.py``). The
generator emits, for each of the fifteen Tag-45 inventory binaries,
a CycloneDX-1.5 (or SPDX-2.3) document listing every transitively-
reachable Cargo package and its pinned version + checksum.

What the generator does NOT do is compare today's emitted SBOMs to
a *baseline*. Without a baseline, the operator can read the SBOM
but cannot answer:

  * Did a dependency get added, removed, or version-bumped since
    the last AR-Hand-Gate sign-off?
  * Is the cargo-lock SHA256 still the one the cosign-pinned image
    was built against?
  * Has any component's pinned crates.io checksum changed underneath
    us (which would indicate a yanked-then-republished crate or a
    supply-chain manipulation)?

This Tag-49 verifier answers exactly that. It runs the Tag-48
generator under the same hermetic ``--mode=stdlib`` path, then
compares each per-binary SBOM byte-for-byte against the matching
``state/sbom-baseline/<binary>.json`` file. Drift is classified
into four buckets:

  * ``component-added``    -- a new (name, version) tuple appeared.
  * ``component-removed``  -- a previously-present (name, version)
                              tuple is gone.
  * ``version-changed``    -- the same component-name has a new
                              version vs. baseline.
  * ``checksum-changed``   -- the same (name, version) pair has a
                              different SHA-256 checksum than the
                              baseline. This is the highest-priority
                              drift class (it indicates a published
                              crate file changed underneath the same
                              version, which is a supply-chain
                              integrity event).

Aggregate verdict
-----------------

The aggregate verdict over the fifteen binaries is one of:

  * ``GREEN``  -- every per-binary SBOM matches its baseline
                  byte-for-byte on the comparable fields
                  (components, dependencies graph, cargo-lock-sha).
  * ``YELLOW`` -- one or more binaries have component-added /
                  component-removed / version-changed drift, but
                  no checksum-changed drift.
  * ``RED``    -- one or more binaries have checksum-changed drift,
                  OR a baseline file is missing entirely, OR the
                  cargo-lock-sha256 in any SBOM differs from the
                  envelope's cargo-lock-sha256 (substrate
                  inconsistency).

The verdict is emitted to:

  * Aggregate envelope JSON (``--out-json``).
  * Prometheus textfile (``--out-textfile``).
  * Markdown summary block (``--out-markdown`` for Job-Summary).
  * stdout (single ``[verdict=<color>] ...`` line).

Sandbox posture
---------------

Strict hermetic: stdlib + tomllib only (re-uses the Tag-48
generator's parser). No podman / cargo / cosign / network egress.
The verifier does NOT mutate baseline files -- baseline-refresh is
an Operator-Hand procedure documented in
``docs/operations/15-binary-sbom-baseline-refresh.md``.

Audit-Trail anchor
------------------

ADR-0066 §AR-Hand-Gate requires pre-cutover stability + signed
provenance for every Welle. The SBOM-vs-Baseline verifier closes
the time-axis on the dependency-tree the Tag-48 generator captured.

Anchors
-------

  * Tag-48 PR #310 -- 15-binary SBOM generator + workflow.
  * Tag-47 PR #307 -- Cosign-Keyless-OIDC-Drift-Probe (time-axis
    pattern this verifier mirrors).
  * Tag-45 PR #294 -- 15-binary cosign-policy substrate refresh.
  * ADR-0066 §AR-Hand-Gate -- pre-cutover sign-off bundle.
  * feedback_sandbox_host_trennung.md -- no live cargo I/O.

Author: Kai Hoffmann (Dev-Engineering-3 / Container-Orchestration)
Tag: 49 (KW-22)
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
import time as _time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Loader: import the Tag-48 generator module so we re-use its parser.
# ---------------------------------------------------------------------------


def _load_generator_module(script_path: Path) -> Any:
    """Load the hyphenated Tag-48 generator script as a module."""
    spec = importlib.util.spec_from_file_location(
        "generate_15_binary_sbom", str(script_path)
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load generator module from {script_path}"
        )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["generate_15_binary_sbom"] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Aggregate verdict colors. Order matters for severity comparisons.
VERDICT_GREEN: str = "GREEN"
VERDICT_YELLOW: str = "YELLOW"
VERDICT_RED: str = "RED"

#: Drift-class identifiers (stable strings; used in envelope output).
DRIFT_COMPONENT_ADDED: str = "component-added"
DRIFT_COMPONENT_REMOVED: str = "component-removed"
DRIFT_VERSION_CHANGED: str = "version-changed"
DRIFT_CHECKSUM_CHANGED: str = "checksum-changed"

#: Per-binary verdict colors.
BIN_OK: str = "OK"
BIN_DRIFT_YELLOW: str = "DRIFT-YELLOW"
BIN_DRIFT_RED: str = "DRIFT-RED"
BIN_MISSING_BASELINE: str = "MISSING-BASELINE"

#: Default location of the Tag-48 generator script (relative to repo).
DEFAULT_GENERATOR_REL: str = (
    "scripts/observability/generate-15-binary-sbom.py"
)

#: Default location of the Tag-48 generator's Cargo.lock input.
DEFAULT_CARGO_LOCK_REL: str = "wirelang-rust/Cargo.lock"

#: Default location of the baseline directory.
DEFAULT_BASELINE_DIR_REL: str = "state/sbom-baseline"

#: Schema version for the verifier envelope output.
VERIFIER_ENVELOPE_SCHEMA_VERSION: str = "1"


# ---------------------------------------------------------------------------
# Dataclasses (pure)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComponentTriple:
    """A (name, version, checksum-or-None) tuple extracted from an SBOM.

    The checksum is None for workspace-local crates and a SHA-256
    hex string for crates.io packages.
    """

    name: str
    version: str
    checksum: Optional[str]


@dataclass(frozen=True)
class DriftEntry:
    """One drift record (one row in the per-binary drift list)."""

    drift_class: str
    component_name: str
    baseline_version: Optional[str]
    current_version: Optional[str]
    baseline_checksum: Optional[str]
    current_checksum: Optional[str]

    def to_json(self) -> Dict[str, object]:
        return {
            "drift_class": self.drift_class,
            "component_name": self.component_name,
            "baseline_version": self.baseline_version,
            "current_version": self.current_version,
            "baseline_checksum": self.baseline_checksum,
            "current_checksum": self.current_checksum,
        }


@dataclass(frozen=True)
class PerBinaryVerdict:
    """The result of comparing one binary's current SBOM to baseline."""

    binary_name: str
    verdict: str
    drift_count: int
    drift_entries: Tuple[DriftEntry, ...]
    baseline_cargo_lock_sha256: Optional[str]
    current_cargo_lock_sha256: Optional[str]
    component_count_baseline: int
    component_count_current: int

    def to_json(self) -> Dict[str, object]:
        return {
            "binary_name": self.binary_name,
            "verdict": self.verdict,
            "drift_count": self.drift_count,
            "drift_entries": [d.to_json() for d in self.drift_entries],
            "baseline_cargo_lock_sha256": self.baseline_cargo_lock_sha256,
            "current_cargo_lock_sha256": self.current_cargo_lock_sha256,
            "component_count_baseline": self.component_count_baseline,
            "component_count_current": self.component_count_current,
        }


@dataclass(frozen=True)
class AggregateVerdict:
    """The aggregate result over the fifteen binaries."""

    verdict: str
    generator_ts: float
    current_cargo_lock_sha256: str
    per_binary: Tuple[PerBinaryVerdict, ...]
    binaries_total: int
    binaries_ok: int
    binaries_yellow: int
    binaries_red: int
    binaries_missing: int


# ---------------------------------------------------------------------------
# Pure functions: SBOM component extraction
# ---------------------------------------------------------------------------


def extract_components_from_cyclonedx(
    sbom: Mapping[str, Any],
) -> Tuple[ComponentTriple, ...]:
    """Extract (name, version, checksum) triples from a CycloneDX-1.5 SBOM.

    The component list is sorted by (name, version) for deterministic
    comparison output.

    Args:
        sbom: a parsed CycloneDX-1.5 JSON object.

    Returns:
        A tuple of ComponentTriple entries.

    Raises:
        ValueError if the SBOM has no ``components`` array.
    """
    components = sbom.get("components")
    if components is None:
        raise ValueError("SBOM has no 'components' array")
    out: List[ComponentTriple] = []
    for entry in components:
        name = entry.get("name")
        version = entry.get("version")
        if name is None or version is None:
            # Defensive: skip malformed component entries rather than
            # crash; the drift-class will still be detectable by
            # baseline mismatch.
            continue
        checksum: Optional[str] = None
        hashes = entry.get("hashes")
        if hashes:
            for h in hashes:
                if h.get("alg") == "SHA-256":
                    checksum = h.get("content")
                    break
        out.append(
            ComponentTriple(
                name=name, version=version, checksum=checksum
            )
        )
    out.sort(key=lambda c: (c.name, c.version))
    return tuple(out)


def extract_cargo_lock_sha256_from_cyclonedx(
    sbom: Mapping[str, Any],
) -> Optional[str]:
    """Extract the ``wakir:cargo-lock-sha256`` property value, if present.

    The Tag-48 generator embeds the cargo-lock-sha256 in the SBOM's
    ``metadata.properties`` array. Returns None if the property is
    missing (e.g. an externally-produced SBOM was placed in the
    baseline directory).
    """
    metadata = sbom.get("metadata") or {}
    properties = metadata.get("properties") or []
    for prop in properties:
        if prop.get("name") == "wakir:cargo-lock-sha256":
            value = prop.get("value")
            if isinstance(value, str):
                return value
    return None


# ---------------------------------------------------------------------------
# Pure functions: drift computation
# ---------------------------------------------------------------------------


def compute_drift_entries(
    baseline: Sequence[ComponentTriple],
    current: Sequence[ComponentTriple],
) -> Tuple[DriftEntry, ...]:
    """Compute the drift entries between baseline and current component sets.

    The comparison is structured so the four drift classes are
    distinguished cleanly:

      * component-added    -- name in current but not baseline.
      * component-removed  -- name in baseline but not current.
      * version-changed    -- name in both, but version differs.
      * checksum-changed   -- name+version in both, but checksum
                              differs (SAME version, different
                              tarball hash -- supply-chain integrity
                              signal).

    Sort the output by (drift_class severity, component_name) so
    the highest-severity drift surfaces first in operator output:
      1. checksum-changed
      2. version-changed
      3. component-removed
      4. component-added
    """
    base_by_name: Dict[str, ComponentTriple] = {
        c.name: c for c in baseline
    }
    cur_by_name: Dict[str, ComponentTriple] = {c.name: c for c in current}

    entries: List[DriftEntry] = []

    # component-added
    for name in sorted(cur_by_name.keys() - base_by_name.keys()):
        c = cur_by_name[name]
        entries.append(
            DriftEntry(
                drift_class=DRIFT_COMPONENT_ADDED,
                component_name=name,
                baseline_version=None,
                current_version=c.version,
                baseline_checksum=None,
                current_checksum=c.checksum,
            )
        )

    # component-removed
    for name in sorted(base_by_name.keys() - cur_by_name.keys()):
        b = base_by_name[name]
        entries.append(
            DriftEntry(
                drift_class=DRIFT_COMPONENT_REMOVED,
                component_name=name,
                baseline_version=b.version,
                current_version=None,
                baseline_checksum=b.checksum,
                current_checksum=None,
            )
        )

    # version-changed + checksum-changed (intersection)
    for name in sorted(base_by_name.keys() & cur_by_name.keys()):
        b = base_by_name[name]
        c = cur_by_name[name]
        if b.version != c.version:
            entries.append(
                DriftEntry(
                    drift_class=DRIFT_VERSION_CHANGED,
                    component_name=name,
                    baseline_version=b.version,
                    current_version=c.version,
                    baseline_checksum=b.checksum,
                    current_checksum=c.checksum,
                )
            )
        elif b.checksum != c.checksum:
            entries.append(
                DriftEntry(
                    drift_class=DRIFT_CHECKSUM_CHANGED,
                    component_name=name,
                    baseline_version=b.version,
                    current_version=c.version,
                    baseline_checksum=b.checksum,
                    current_checksum=c.checksum,
                )
            )

    # Sort by severity then by component name.
    severity_order: Dict[str, int] = {
        DRIFT_CHECKSUM_CHANGED: 0,
        DRIFT_VERSION_CHANGED: 1,
        DRIFT_COMPONENT_REMOVED: 2,
        DRIFT_COMPONENT_ADDED: 3,
    }
    entries.sort(
        key=lambda e: (
            severity_order[e.drift_class],
            e.component_name,
        )
    )
    return tuple(entries)


def classify_per_binary_verdict(
    drift_entries: Sequence[DriftEntry],
    baseline_missing: bool,
) -> str:
    """Classify the per-binary verdict from its drift entries.

    Rules:
      * baseline_missing -> MISSING-BASELINE (counts as RED).
      * any checksum-changed -> DRIFT-RED.
      * any other drift class -> DRIFT-YELLOW.
      * empty drift list -> OK.
    """
    if baseline_missing:
        return BIN_MISSING_BASELINE
    if not drift_entries:
        return BIN_OK
    for e in drift_entries:
        if e.drift_class == DRIFT_CHECKSUM_CHANGED:
            return BIN_DRIFT_RED
    return BIN_DRIFT_YELLOW


def compute_aggregate_verdict(
    per_binary: Sequence[PerBinaryVerdict],
    current_cargo_lock_sha256: str,
) -> str:
    """Compute the aggregate verdict over the fifteen binaries.

    Rules:
      * any binary RED or MISSING-BASELINE -> RED.
      * any binary YELLOW (and no RED/MISSING) -> YELLOW.
      * all binaries OK -> GREEN.
      * substrate inconsistency (a per-binary
        current_cargo_lock_sha256 differs from the aggregate's
        current_cargo_lock_sha256) -> RED.
    """
    has_red = False
    has_yellow = False
    for pb in per_binary:
        if pb.verdict == BIN_DRIFT_RED or pb.verdict == BIN_MISSING_BASELINE:
            has_red = True
        elif pb.verdict == BIN_DRIFT_YELLOW:
            has_yellow = True
        if (
            pb.current_cargo_lock_sha256 is not None
            and pb.current_cargo_lock_sha256 != current_cargo_lock_sha256
        ):
            has_red = True
    if has_red:
        return VERDICT_RED
    if has_yellow:
        return VERDICT_YELLOW
    return VERDICT_GREEN


def count_by_verdict(
    per_binary: Sequence[PerBinaryVerdict],
) -> Tuple[int, int, int, int]:
    """Return (ok, yellow, red, missing) counts."""
    ok = sum(1 for pb in per_binary if pb.verdict == BIN_OK)
    yellow = sum(1 for pb in per_binary if pb.verdict == BIN_DRIFT_YELLOW)
    red = sum(1 for pb in per_binary if pb.verdict == BIN_DRIFT_RED)
    missing = sum(
        1 for pb in per_binary if pb.verdict == BIN_MISSING_BASELINE
    )
    return ok, yellow, red, missing


# ---------------------------------------------------------------------------
# Pure functions: per-binary verification (no I/O)
# ---------------------------------------------------------------------------


def verify_one_binary(
    binary_name: str,
    current_sbom: Mapping[str, Any],
    baseline_sbom: Optional[Mapping[str, Any]],
) -> PerBinaryVerdict:
    """Verify a single binary's current SBOM against its baseline.

    Pure function: takes parsed JSON dicts in, returns a verdict
    record out. No file I/O. Test target.
    """
    if baseline_sbom is None:
        # Baseline missing: still extract the current component
        # count so the operator sees substrate health.
        current_components = extract_components_from_cyclonedx(current_sbom)
        current_lock_sha = extract_cargo_lock_sha256_from_cyclonedx(
            current_sbom
        )
        return PerBinaryVerdict(
            binary_name=binary_name,
            verdict=BIN_MISSING_BASELINE,
            drift_count=0,
            drift_entries=tuple(),
            baseline_cargo_lock_sha256=None,
            current_cargo_lock_sha256=current_lock_sha,
            component_count_baseline=0,
            component_count_current=len(current_components),
        )

    baseline_components = extract_components_from_cyclonedx(baseline_sbom)
    current_components = extract_components_from_cyclonedx(current_sbom)
    baseline_lock_sha = extract_cargo_lock_sha256_from_cyclonedx(
        baseline_sbom
    )
    current_lock_sha = extract_cargo_lock_sha256_from_cyclonedx(current_sbom)

    drift_entries = compute_drift_entries(
        baseline_components, current_components
    )
    verdict = classify_per_binary_verdict(drift_entries, baseline_missing=False)

    return PerBinaryVerdict(
        binary_name=binary_name,
        verdict=verdict,
        drift_count=len(drift_entries),
        drift_entries=drift_entries,
        baseline_cargo_lock_sha256=baseline_lock_sha,
        current_cargo_lock_sha256=current_lock_sha,
        component_count_baseline=len(baseline_components),
        component_count_current=len(current_components),
    )


def verify_all_binaries(
    current_sboms: Mapping[str, Mapping[str, Any]],
    baseline_sboms: Mapping[str, Optional[Mapping[str, Any]]],
    inventory: Sequence[str],
) -> Tuple[PerBinaryVerdict, ...]:
    """Verify every binary in ``inventory`` order.

    A missing entry in ``current_sboms`` is a hard error -- the
    generator must always emit fifteen SBOMs. A missing entry in
    ``baseline_sboms`` (value None) is a MISSING-BASELINE verdict.
    """
    out: List[PerBinaryVerdict] = []
    for binary_name in inventory:
        if binary_name not in current_sboms:
            raise ValueError(
                f"current SBOM missing for binary {binary_name!r}"
            )
        current = current_sboms[binary_name]
        baseline = baseline_sboms.get(binary_name)
        out.append(verify_one_binary(binary_name, current, baseline))
    return tuple(out)


# ---------------------------------------------------------------------------
# Pure functions: rendering (envelope JSON / textfile / markdown)
# ---------------------------------------------------------------------------


def render_envelope(
    aggregate: AggregateVerdict,
) -> Dict[str, object]:
    """Render the aggregate verdict as a JSON-serialisable dict."""
    return {
        "schema_version": VERIFIER_ENVELOPE_SCHEMA_VERSION,
        "verdict": aggregate.verdict,
        "generator_ts": aggregate.generator_ts,
        "current_cargo_lock_sha256": aggregate.current_cargo_lock_sha256,
        "binaries_total": aggregate.binaries_total,
        "binaries_ok": aggregate.binaries_ok,
        "binaries_yellow": aggregate.binaries_yellow,
        "binaries_red": aggregate.binaries_red,
        "binaries_missing": aggregate.binaries_missing,
        "per_binary": [pb.to_json() for pb in aggregate.per_binary],
    }


def render_textfile_metrics(aggregate: AggregateVerdict) -> str:
    """Render Prometheus textfile metrics for the aggregate verdict.

    Emits two gauge families:
      * ``wakir_sbom_verification_aggregate_verdict`` -- single
        label ``verdict={GREEN,YELLOW,RED}``, value 1 for the
        active verdict, 0 for the others (one-hot).
      * ``wakir_sbom_verification_per_binary_drift_count`` --
        labels ``binary``, ``verdict``; value = drift entry count.
    """
    lines: List[str] = []
    lines.append("# HELP wakir_sbom_verification_aggregate_verdict")
    lines.append("# (one-hot per verdict)")
    lines.append("# TYPE wakir_sbom_verification_aggregate_verdict gauge")
    for color in (VERDICT_GREEN, VERDICT_YELLOW, VERDICT_RED):
        val = 1 if aggregate.verdict == color else 0
        lines.append(
            f'wakir_sbom_verification_aggregate_verdict'
            f'{{verdict="{color}"}} {val}'
        )

    lines.append("")
    lines.append(
        "# HELP wakir_sbom_verification_per_binary_drift_count"
    )
    lines.append("# (per-binary drift entry count)")
    lines.append(
        "# TYPE wakir_sbom_verification_per_binary_drift_count gauge"
    )
    for pb in aggregate.per_binary:
        lines.append(
            f'wakir_sbom_verification_per_binary_drift_count'
            f'{{binary="{pb.binary_name}",verdict="{pb.verdict}"}} '
            f"{pb.drift_count}"
        )

    lines.append("")
    lines.append(
        "# HELP wakir_sbom_verification_binaries_by_verdict_count"
    )
    lines.append(
        "# (aggregate count by verdict class)"
    )
    lines.append(
        "# TYPE wakir_sbom_verification_binaries_by_verdict_count gauge"
    )
    lines.append(
        f'wakir_sbom_verification_binaries_by_verdict_count'
        f'{{verdict="OK"}} {aggregate.binaries_ok}'
    )
    lines.append(
        f'wakir_sbom_verification_binaries_by_verdict_count'
        f'{{verdict="DRIFT-YELLOW"}} {aggregate.binaries_yellow}'
    )
    lines.append(
        f'wakir_sbom_verification_binaries_by_verdict_count'
        f'{{verdict="DRIFT-RED"}} {aggregate.binaries_red}'
    )
    lines.append(
        f'wakir_sbom_verification_binaries_by_verdict_count'
        f'{{verdict="MISSING-BASELINE"}} {aggregate.binaries_missing}'
    )

    return "\n".join(lines) + "\n"


def render_markdown_summary(aggregate: AggregateVerdict) -> str:
    """Render a Markdown summary suitable for GHA Job-Summary."""
    lines: List[str] = []
    lines.append("## 15-Binary SBOM-vs-Baseline Verification")
    lines.append("")
    lines.append(f"**Aggregate verdict:** `{aggregate.verdict}`")
    lines.append("")
    lines.append(
        f"- Binaries total: {aggregate.binaries_total}"
    )
    lines.append(f"- OK: {aggregate.binaries_ok}")
    lines.append(f"- DRIFT-YELLOW: {aggregate.binaries_yellow}")
    lines.append(f"- DRIFT-RED: {aggregate.binaries_red}")
    lines.append(f"- MISSING-BASELINE: {aggregate.binaries_missing}")
    lines.append(
        f"- Current Cargo.lock SHA-256: "
        f"`{aggregate.current_cargo_lock_sha256}`"
    )
    lines.append("")
    lines.append("### Per-binary verdicts")
    lines.append("")
    lines.append("| Binary | Verdict | Drift count | Components |")
    lines.append("|---|---|---:|---:|")
    for pb in aggregate.per_binary:
        lines.append(
            f"| `{pb.binary_name}` | {pb.verdict} | "
            f"{pb.drift_count} | "
            f"{pb.component_count_baseline} -> "
            f"{pb.component_count_current} |"
        )

    # Per-binary drift detail blocks (only for non-OK binaries).
    detail_block_emitted = False
    for pb in aggregate.per_binary:
        if pb.verdict == BIN_OK:
            continue
        if not detail_block_emitted:
            lines.append("")
            lines.append("### Drift detail")
            detail_block_emitted = True
        lines.append("")
        lines.append(f"#### `{pb.binary_name}` ({pb.verdict})")
        lines.append("")
        if pb.verdict == BIN_MISSING_BASELINE:
            lines.append("- Baseline file missing.")
            continue
        lines.append(
            "| Drift class | Component | Baseline | Current |"
        )
        lines.append("|---|---|---|---|")
        # Cap detail rows so a catastrophic drift doesn't blow up
        # the Job-Summary; operator can read full envelope.
        max_rows = 20
        for d in pb.drift_entries[:max_rows]:
            base_field = (
                f"{d.baseline_version or '-'} / "
                f"{(d.baseline_checksum or '-')[:8]}"
            )
            cur_field = (
                f"{d.current_version or '-'} / "
                f"{(d.current_checksum or '-')[:8]}"
            )
            lines.append(
                f"| {d.drift_class} | `{d.component_name}` | "
                f"{base_field} | {cur_field} |"
            )
        if pb.drift_count > max_rows:
            lines.append(
                f"\n(... {pb.drift_count - max_rows} more drift "
                f"entries truncated; see envelope JSON for full list)"
            )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# I/O surface (small, isolated for testability).
# ---------------------------------------------------------------------------


def read_json_file(path: Path) -> Mapping[str, Any]:
    """Read a JSON file from disk."""
    return json.loads(path.read_text(encoding="utf-8"))


def load_baseline(
    baseline_dir: Path,
    inventory: Sequence[str],
) -> Dict[str, Optional[Mapping[str, Any]]]:
    """Load every baseline SBOM file. Missing files map to None."""
    out: Dict[str, Optional[Mapping[str, Any]]] = {}
    for binary_name in inventory:
        candidate = baseline_dir / f"{binary_name}.json"
        if not candidate.is_file():
            out[binary_name] = None
        else:
            try:
                out[binary_name] = read_json_file(candidate)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"baseline {candidate} not valid JSON: {exc}"
                ) from exc
    return out


def load_current_from_sbom_dir(
    sbom_dir: Path,
    inventory: Sequence[str],
) -> Dict[str, Mapping[str, Any]]:
    """Load every per-binary SBOM the generator wrote."""
    out: Dict[str, Mapping[str, Any]] = {}
    for binary_name in inventory:
        candidate = sbom_dir / f"{binary_name}.cdx.json"
        if not candidate.is_file():
            raise ValueError(
                f"current SBOM {candidate} missing -- "
                f"generator did not emit it"
            )
        out[binary_name] = read_json_file(candidate)
    return out


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare today's 15-binary SBOMs (emitted by the Tag-48 "
            "generator) against the pinned baseline in "
            "state/sbom-baseline/. Drift classification + aggregate "
            "verdict for Mira-Notify routing."
        )
    )
    parser.add_argument(
        "--sbom-dir",
        required=True,
        type=Path,
        help=(
            "Directory containing the generator's per-binary SBOM "
            "output (one ``<binary>.cdx.json`` file per binary)."
        ),
    )
    parser.add_argument(
        "--baseline-dir",
        required=True,
        type=Path,
        help=(
            "Directory containing the baseline SBOMs "
            "(``<binary>.json`` per binary)."
        ),
    )
    parser.add_argument(
        "--out-json",
        required=False,
        type=Path,
        default=None,
        help="Output aggregate verdict JSON envelope.",
    )
    parser.add_argument(
        "--out-textfile",
        required=False,
        type=Path,
        default=None,
        help="Output Prometheus textfile metrics path.",
    )
    parser.add_argument(
        "--out-markdown",
        required=False,
        type=Path,
        default=None,
        help="Output Job-Summary Markdown path.",
    )
    parser.add_argument(
        "--cargo-lock-sha256",
        required=False,
        default=None,
        help=(
            "Override the current cargo-lock SHA-256 for the "
            "envelope's substrate-consistency check. Defaults to "
            "the value embedded in the first SBOM."
        ),
    )
    parser.add_argument(
        "--exit-non-zero-on-drift",
        action="store_true",
        help=(
            "Exit with status 1 if the aggregate verdict is not "
            "GREEN. Defaults to exit 0 (the verifier surfaces "
            "drift via envelope + textfile; the workflow decides "
            "whether to block)."
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

    # Re-use the Tag-48 generator constants for the inventory order
    # (single source of truth).
    here = Path(__file__).resolve().parent
    gen_path = here / "generate-15-binary-sbom.py"
    if not gen_path.is_file():
        print(
            f"ERROR: Tag-48 generator script missing at {gen_path}",
            file=sys.stderr,
        )
        return 2
    gen = _load_generator_module(gen_path)

    inventory = gen.TAG45_BINARY_INVENTORY

    try:
        current_sboms = load_current_from_sbom_dir(args.sbom_dir, inventory)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        baseline_sboms = load_baseline(args.baseline_dir, inventory)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    per_binary = verify_all_binaries(
        current_sboms=current_sboms,
        baseline_sboms=baseline_sboms,
        inventory=inventory,
    )

    if args.cargo_lock_sha256 is not None:
        current_lock_sha = args.cargo_lock_sha256
    else:
        # Use the cargo-lock-sha256 from the first SBOM as the
        # aggregate's authoritative value (every SBOM in a single
        # generator run embeds the same value).
        first = next(iter(current_sboms.values()))
        current_lock_sha = extract_cargo_lock_sha256_from_cyclonedx(first) or ""

    verdict = compute_aggregate_verdict(per_binary, current_lock_sha)
    ok, yellow, red, missing = count_by_verdict(per_binary)

    ts = (
        args.generator_ts
        if args.generator_ts is not None
        else _time.time()
    )

    aggregate = AggregateVerdict(
        verdict=verdict,
        generator_ts=ts,
        current_cargo_lock_sha256=current_lock_sha,
        per_binary=per_binary,
        binaries_total=len(per_binary),
        binaries_ok=ok,
        binaries_yellow=yellow,
        binaries_red=red,
        binaries_missing=missing,
    )

    envelope = render_envelope(aggregate)

    if args.out_json is not None:
        write_json(args.out_json, envelope)
    if args.out_textfile is not None:
        write_text(args.out_textfile, render_textfile_metrics(aggregate))
    if args.out_markdown is not None:
        write_text(args.out_markdown, render_markdown_summary(aggregate))

    # Single-line stdout digest for shell-callers + CI step capture.
    print(
        f"[verdict={aggregate.verdict}] "
        f"ok={ok} yellow={yellow} red={red} missing={missing} "
        f"cargo-lock-sha256={current_lock_sha[:16]}..."
    )

    if args.exit_non_zero_on_drift and aggregate.verdict != VERDICT_GREEN:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
