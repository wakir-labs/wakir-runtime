#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Cross-repo compatibility gate: protocol ↔ runtime ↔ verify.

Replaces the byte-level ``cross-repo-drift-audit`` (SHA-256 on 10 file
pairs, audit-only) with four substantive checks, all enforced:

======  =============================================================
Level   What is checked
======  =============================================================
schema  Every ``wirelang/schemas/*.json`` has a counterpart in
        ``wakir_protocol/schemas/`` with the same canonical digest
        (JCS after stripping ``x-spdx-*`` and ``description`` at every
        level, see ``compat_canonical``). Protocol schemas marked
        ``x-status: stub`` are reported as ``deferred`` (not yet
        canonical). Drift is a failure unless covered by an active,
        time-boxed allowlist entry.
vector  ``tests/fixtures/proof-path-vectors/vector-*.json`` from
        protocol are reproduced with ``wat.merkle.aggregator`` (leaf
        hashes, levels, root, sibling paths) and independently with
        ``wakir_verify.merkle_proof``; every embedded proof document
        validates against the inclusion-proof schema; the tampered
        case must *not* verify.
manif.  The manifest written by the runtime aggregator during
        ``make demo-proof`` validates against the protocol manifest
        schema, carries ``MANIFEST_VERSION``, loads through
        ``wakir_verify.manifest`` with a re-derived root equal to the
        recorded one, and the runtime verify CLI reproduces the
        emitted sibling path. The field divergence ``version`` /
        ``hour_slot`` (runtime) vs. ``envelope`` / ``hour``
        (verify loader, optional) is pinned as constraint C1.
proof   ``proof.json`` from ``make demo-proof`` validates against the
        protocol ``wakir-inclusion-proof-v1.json``. While that file is
        a stub, the runtime draft is used as fallback and the log says
        so. The proof must resolve to the manifest root under
        ``wakir_verify.merkle_proof.verify_merkle_proof``.
======  =============================================================

Exit code 0 when no finding has status ``fail``; 1 otherwise. A
missing dependency (``jsonschema``, ``wakir_verify``, the protocol or
verify checkout) is a ``fail`` at level ``setup`` — the gate never
downgrades itself to audit-only.

Usage (CI)::

    python3 tooling/compat/check_compat.py \
        --protocol "$RUNNER_TEMP/wakir-protocol" \
        --verify   "$RUNNER_TEMP/wakir-verify" \
        --demo-workdir "$RUNNER_TEMP/demo-proof" \
        --summary-md "$RUNNER_TEMP/compat-summary.md"
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import compat_allowlist as allowlist_mod  # noqa: E402
import compat_canonical as canon  # noqa: E402

REPO_ROOT_DEFAULT = _HERE.parents[1]
ALLOWLIST_DEFAULT = _HERE / "compat-allowlist.json"

RUNTIME_SCHEMA_DIR = Path("wirelang/schemas")
PROTOCOL_SCHEMA_DIR = Path("wakir_protocol/schemas")
PROTOCOL_VECTOR_DIR = Path("tests/fixtures/proof-path-vectors")
PROOF_SCHEMA_FILE = "wakir-inclusion-proof-v1.json"
MANIFEST_SCHEMA_FILE = "wakir-wat-manifest-v1.json"
PROOF_SCHEMA_ID = "wakir-inclusion-proof/v1"
VECTOR_SCHEMA_ID = "wakir-proof-path-vector/v1"

STATUS_OK = "ok"
STATUS_ALLOWED = "allowed"
STATUS_DEFERRED = "deferred"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

LEVELS = ("setup", "schema", "vector", "manifest", "proof", "allowlist")

#: Constraint C1 — pinned field divergence between the runtime manifest
#: writer and the wakir-verify loader. Changing either side without
#: updating the other trips the manifest level.
CONSTRAINT_C1 = (
    "runtime writes `version` + `hour_slot`; wakir_verify.manifest reads the "
    "optional `envelope` (default '') + `hour` (default None) and ignores "
    "`version`/`hour_slot`; both sides agree on `merkle_root` + `leaves[].{event_id,leaf_hash}`"
)


# ---------------------------------------------------------------------------
# Findings / report
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    level: str
    status: str
    subject: str
    detail: str = ""


@dataclass
class Report:
    protocol_head: str = "unknown"
    verify_head: str = "unknown"
    runtime_head: str = "unknown"
    proof_schema_source: str = "unset"
    findings: list[Finding] = field(default_factory=list)

    def add(self, level: str, status: str, subject: str, detail: str = "") -> Finding:
        finding = Finding(level=level, status=status, subject=subject, detail=detail)
        self.findings.append(finding)
        return finding

    def extend(self, findings: Iterable[Finding]) -> None:
        self.findings.extend(findings)

    def has_fail(self) -> bool:
        return any(f.status == STATUS_FAIL for f in self.findings)

    def counts(self) -> dict[str, int]:
        out = {s: 0 for s in (STATUS_OK, STATUS_ALLOWED, STATUS_DEFERRED, STATUS_WARN, STATUS_FAIL)}
        for f in self.findings:
            out[f.status] = out.get(f.status, 0) + 1
        return out

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": "wakir-compat-report/v1",
            "protocol_head": self.protocol_head,
            "verify_head": self.verify_head,
            "runtime_head": self.runtime_head,
            "proof_schema_source": self.proof_schema_source,
            "verdict": STATUS_FAIL if self.has_fail() else STATUS_OK,
            "counts": self.counts(),
            "findings": [asdict(f) for f in self.findings],
        }

    def render_markdown(self) -> str:
        counts = self.counts()
        verdict = "FAIL" if self.has_fail() else "PASS"
        lines = [
            "## cross-repo compatibility (protocol ↔ runtime ↔ verify)",
            "",
            f"**Verdict:** {verdict} — ok={counts[STATUS_OK]} allowed={counts[STATUS_ALLOWED]} "
            f"deferred={counts[STATUS_DEFERRED]} warn={counts[STATUS_WARN]} fail={counts[STATUS_FAIL]}",
            "",
            f"- wakir-protocol @ `{self.protocol_head}`",
            f"- wakir-verify @ `{self.verify_head}`",
            f"- wakir-runtime @ `{self.runtime_head}`",
            f"- inclusion-proof schema source: {self.proof_schema_source}",
            "",
            "| Level | Status | Subject | Detail |",
            "|---|---|---|---|",
        ]
        for f in self.findings:
            detail = f.detail.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {f.level} | {f.status} | `{f.subject}` | {detail} |")
        lines.append("")
        return "\n".join(lines)

    def render_text(self) -> str:
        width = max((len(f.subject) for f in self.findings), default=10)
        out = []
        for f in self.findings:
            out.append(f"[{f.status:8}] {f.level:8} {f.subject:<{width}}  {f.detail}")
        counts = self.counts()
        out.append(
            "compat: "
            + " ".join(f"{k}={v}" for k, v in counts.items())
            + f" verdict={'FAIL' if self.has_fail() else 'PASS'}"
        )
        return "\n".join(out)


def git_head(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


# ---------------------------------------------------------------------------
# Dependency wiring
# ---------------------------------------------------------------------------


def _jsonschema():
    try:
        import jsonschema  # type: ignore
    except ImportError:  # pragma: no cover - exercised only in broken envs
        return None
    return jsonschema


def validate_instance(schema: dict[str, Any], instance: Any) -> list[str]:
    """Return a list of validation error messages (empty when valid)."""
    js = _jsonschema()
    if js is None:
        return ["jsonschema is not installed"]
    validator_cls = js.validators.validator_for(schema)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    out = []
    for err in errors:
        where = "/".join(str(p) for p in err.path) or "<root>"
        out.append(f"{where}: {err.message}")
    return out


@dataclass
class VerifyModules:
    manifest: Any
    merkle_proof: Any
    location: str


def import_verify(verify_root: Optional[Path]) -> VerifyModules:
    """Import ``wakir_verify`` preferring the checkout at ``verify_root``."""
    if verify_root is not None:
        sys.path.insert(0, str(verify_root))
    manifest = importlib.import_module("wakir_verify.manifest")
    merkle_proof = importlib.import_module("wakir_verify.merkle_proof")
    pkg = importlib.import_module("wakir_verify")
    return VerifyModules(
        manifest=manifest,
        merkle_proof=merkle_proof,
        location=str(Path(pkg.__file__).resolve().parent),
    )


def import_runtime(runtime_root: Path):
    """Import the runtime modules the gate needs (``wat.*``)."""
    if str(runtime_root) not in sys.path:
        sys.path.insert(0, str(runtime_root))
    aggregator = importlib.import_module("wat.merkle.aggregator")
    aggregator_cli = importlib.import_module("wat.cmd.aggregator_cli")
    verify_cli = importlib.import_module("wat.verify.cli")
    return aggregator, aggregator_cli, verify_cli


# ---------------------------------------------------------------------------
# Level: inclusion-proof schema selection
# ---------------------------------------------------------------------------


@dataclass
class ProofSchemaChoice:
    schema: dict[str, Any]
    source: str
    stub: Optional[dict[str, Any]] = None


def select_proof_schema(runtime_root: Path, protocol_root: Path) -> tuple[Optional[ProofSchemaChoice], list[Finding]]:
    """Pick the schema ``proof.json`` and vector proofs are validated against.

    Protocol is canonical. While protocol ships a stub (``x-status:
    stub``), the runtime draft is the fallback and the stub is still
    applied as a floor (it is a subset by construction).
    """
    findings: list[Finding] = []
    protocol_path = protocol_root / PROTOCOL_SCHEMA_DIR / PROOF_SCHEMA_FILE
    runtime_path = runtime_root / RUNTIME_SCHEMA_DIR / PROOF_SCHEMA_FILE

    protocol_schema = canon.load_json(protocol_path) if protocol_path.exists() else None
    runtime_schema = canon.load_json(runtime_path) if runtime_path.exists() else None

    if protocol_schema is not None and not canon.is_stub_schema(protocol_schema):
        findings.append(Finding("proof", STATUS_OK, PROOF_SCHEMA_FILE, "protocol canon in force"))
        return ProofSchemaChoice(protocol_schema, "protocol-canon"), findings

    if runtime_schema is None:
        findings.append(
            Finding(
                "proof",
                STATUS_FAIL,
                PROOF_SCHEMA_FILE,
                "neither a canonical protocol schema nor the runtime draft is available",
            )
        )
        return None, findings

    if protocol_schema is None:
        findings.append(
            Finding(
                "proof",
                STATUS_DEFERRED,
                PROOF_SCHEMA_FILE,
                "protocol has no inclusion-proof schema yet; FALLBACK to runtime draft",
            )
        )
        return ProofSchemaChoice(runtime_schema, "runtime-draft (fallback: protocol schema missing)"), findings

    findings.append(
        Finding(
            "proof",
            STATUS_DEFERRED,
            PROOF_SCHEMA_FILE,
            "protocol schema is `x-status: stub`; FALLBACK to runtime draft, stub applied as floor",
        )
    )
    return (
        ProofSchemaChoice(runtime_schema, "runtime-draft (fallback: protocol stub)", stub=protocol_schema),
        findings,
    )


def validate_proof_document(choice: ProofSchemaChoice, proof: Any, subject: str) -> list[Finding]:
    findings: list[Finding] = []
    errors = validate_instance(choice.schema, proof)
    if errors:
        findings.append(Finding("proof", STATUS_FAIL, subject, f"schema violation ({choice.source}): " + "; ".join(errors[:3])))
    else:
        findings.append(Finding("proof", STATUS_OK, subject, f"validates against {choice.source}"))
    if choice.stub is not None:
        stub_errors = validate_instance(choice.stub, proof)
        if stub_errors:
            findings.append(Finding("proof", STATUS_FAIL, subject, "violates protocol stub floor: " + "; ".join(stub_errors[:3])))
    return findings


# ---------------------------------------------------------------------------
# Level: schema
# ---------------------------------------------------------------------------


def check_schemas(
    runtime_root: Path,
    protocol_root: Path,
    active_allow: dict[str, allowlist_mod.AllowlistEntry],
    used_allow: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    runtime_dir = runtime_root / RUNTIME_SCHEMA_DIR
    protocol_dir = protocol_root / PROTOCOL_SCHEMA_DIR

    if not runtime_dir.is_dir():
        return [Finding("schema", STATUS_FAIL, str(RUNTIME_SCHEMA_DIR), "runtime schema directory missing")]
    if not protocol_dir.is_dir():
        return [Finding("schema", STATUS_FAIL, str(PROTOCOL_SCHEMA_DIR), "protocol schema directory missing")]

    runtime_files = sorted(p for p in runtime_dir.glob("*.json") if p.is_file())
    if not runtime_files:
        return [Finding("schema", STATUS_FAIL, str(RUNTIME_SCHEMA_DIR), "no runtime schemas found")]

    for runtime_path in runtime_files:
        rel = (RUNTIME_SCHEMA_DIR / runtime_path.name).as_posix()
        protocol_path = protocol_dir / runtime_path.name
        waiver = active_allow.get(rel)

        try:
            runtime_schema = canon.load_json(runtime_path)
        except (OSError, ValueError) as exc:
            findings.append(Finding("schema", STATUS_FAIL, rel, f"runtime copy unreadable: {exc}"))
            continue

        if not protocol_path.exists():
            if waiver is not None:
                used_allow.add(rel)
                findings.append(Finding("schema", STATUS_ALLOWED, rel, f"no protocol counterpart; allowlisted until {waiver.until} ({waiver.tracking})"))
            else:
                findings.append(Finding("schema", STATUS_FAIL, rel, "no counterpart in protocol"))
            continue

        try:
            protocol_schema = canon.load_json(protocol_path)
        except (OSError, ValueError) as exc:
            findings.append(Finding("schema", STATUS_FAIL, rel, f"protocol copy unreadable: {exc}"))
            continue

        if canon.is_stub_schema(protocol_schema):
            findings.append(Finding("schema", STATUS_DEFERRED, rel, "protocol copy is `x-status: stub` — comparison deferred until canon lands"))
            continue

        runtime_digest = canon.canonical_digest(runtime_schema)
        protocol_digest = canon.canonical_digest(protocol_schema)
        if runtime_digest == protocol_digest:
            findings.append(Finding("schema", STATUS_OK, rel, f"canonical digest {runtime_digest[:12]}"))
        elif waiver is not None:
            used_allow.add(rel)
            findings.append(Finding("schema", STATUS_ALLOWED, rel, f"drift {runtime_digest[:12]} ≠ {protocol_digest[:12]}; allowlisted until {waiver.until} ({waiver.tracking})"))
        else:
            findings.append(Finding("schema", STATUS_FAIL, rel, f"canonical drift: runtime {runtime_digest[:12]} ≠ protocol {protocol_digest[:12]}"))

    runtime_names = {p.name for p in runtime_files}
    for protocol_path in sorted(protocol_dir.glob("*.json")):
        if protocol_path.name not in runtime_names:
            findings.append(Finding("schema", STATUS_WARN, (PROTOCOL_SCHEMA_DIR / protocol_path.name).as_posix(), "protocol schema has no runtime mirror"))
    return findings


# ---------------------------------------------------------------------------
# Level: vectors
# ---------------------------------------------------------------------------


def _hex_list(items: Iterable[bytes]) -> list[str]:
    return [b.hex() for b in items]


def _siblings_from_doc(proof: dict[str, Any]) -> list[tuple[bytes, str]]:
    return [(bytes.fromhex(s["hash"]), s["side"]) for s in proof.get("siblings", [])]


def check_vectors(
    protocol_root: Path,
    aggregator: Any,
    verify: VerifyModules,
    proof_choice: Optional[ProofSchemaChoice],
) -> list[Finding]:
    findings: list[Finding] = []
    vector_dir = protocol_root / PROTOCOL_VECTOR_DIR
    vectors = sorted(vector_dir.glob("vector-*.json")) if vector_dir.is_dir() else []
    if not vectors:
        return [Finding("vector", STATUS_FAIL, PROTOCOL_VECTOR_DIR.as_posix(), "no proof-path vectors in protocol")]

    for path in vectors:
        subject = path.name
        try:
            vec = canon.load_json(path)
        except (OSError, ValueError) as exc:
            findings.append(Finding("vector", STATUS_FAIL, subject, f"unreadable: {exc}"))
            continue
        if vec.get("schema") != VECTOR_SCHEMA_ID:
            findings.append(Finding("vector", STATUS_FAIL, subject, f"unexpected vector schema {vec.get('schema')!r}"))
            continue

        problems: list[str] = []
        leaves = vec.get("leaves") or []
        try:
            leaf_bytes = [
                aggregator.compute_leaf_hash(
                    event_id=leaf["event_id"],
                    time=leaf["time"],
                    payload_hash=leaf["payload_hash"],
                    capability_token_hash=leaf["capability_token_hash"],
                )
                for leaf in leaves
            ]
        except (KeyError, TypeError) as exc:
            findings.append(Finding("vector", STATUS_FAIL, subject, f"leaf tuple malformed: {exc}"))
            continue
        if not leaf_bytes:
            findings.append(Finding("vector", STATUS_FAIL, subject, "vector has no leaves"))
            continue

        if _hex_list(leaf_bytes) != vec.get("leaf_hashes"):
            problems.append("runtime leaf hashes ≠ vector leaf_hashes")

        root, levels = aggregator.build_merkle_tree(leaf_bytes)
        if root.hex() != vec.get("merkle_root"):
            problems.append("runtime root ≠ vector merkle_root")
        if [_hex_list(level) for level in levels] != vec.get("levels"):
            problems.append("runtime tree levels ≠ vector levels")

        verify_root = verify.merkle_proof.root_hash(leaf_bytes)
        if verify_root.hex() != vec.get("merkle_root"):
            problems.append("wakir_verify root ≠ vector merkle_root")

        proofs = vec.get("proofs")
        if proofs is None:
            findings.append(Finding("vector", STATUS_DEFERRED, subject, "vector carries no proofs[]; sibling-path comparison skipped"))
            proofs = []
        elif len(proofs) != len(leaf_bytes):
            problems.append(f"proofs[] has {len(proofs)} entries for {len(leaf_bytes)} leaves")

        for index in range(len(leaf_bytes)):
            runtime_path_ = aggregator.merkle_proof(leaf_bytes, index)
            if not aggregator.verify_merkle_proof(leaf_bytes[index], runtime_path_, root):
                problems.append(f"runtime proof for index {index} does not verify")
            if not verify.merkle_proof.verify_merkle_proof(leaf_bytes[index], runtime_path_, root):
                problems.append(f"wakir_verify rejects runtime proof for index {index}")
            if index < len(proofs):
                doc = proofs[index]
                doc_siblings = _siblings_from_doc(doc)
                if doc_siblings != list(runtime_path_):
                    problems.append(f"proofs[{index}].siblings ≠ runtime sibling path")
                if doc.get("leaf_hash") != leaf_bytes[index].hex():
                    problems.append(f"proofs[{index}].leaf_hash ≠ runtime leaf hash")
                if doc.get("leaf_index") != index or doc.get("leaf_count") != len(leaf_bytes):
                    problems.append(f"proofs[{index}] leaf_index/leaf_count inconsistent")
                if doc.get("merkle_root") != root.hex():
                    problems.append(f"proofs[{index}].merkle_root ≠ runtime root")
                if proof_choice is not None:
                    for f in validate_proof_document(proof_choice, doc, f"{subject}#proofs[{index}]"):
                        if f.status == STATUS_FAIL:
                            problems.append(f.detail)

        for exp in vec.get("expected") or []:
            idx = exp.get("leaf_index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(leaf_bytes):
                problems.append(f"expected[] references leaf_index {idx!r}")
                continue
            actual = aggregator.verify_merkle_proof(leaf_bytes[idx], aggregator.merkle_proof(leaf_bytes, idx), root)
            if actual != exp.get("verified"):
                problems.append(f"expected[{idx}].verified={exp.get('verified')} but runtime says {actual}")

        tampered = vec.get("tampered")
        if tampered is not None:
            try:
                t_leaf = tampered["leaf"]
                t_hash = aggregator.compute_leaf_hash(
                    event_id=t_leaf["event_id"],
                    time=t_leaf["time"],
                    payload_hash=t_leaf["payload_hash"],
                    capability_token_hash=t_leaf["capability_token_hash"],
                )
                if t_hash.hex() != tampered.get("leaf_hash"):
                    problems.append("tampered.leaf_hash ≠ runtime hash of tampered leaf")
                t_siblings = _siblings_from_doc(tampered["proof"])
                expected_verified = bool(tampered.get("expected_verified", False))
                rt = aggregator.verify_merkle_proof(t_hash, t_siblings, root)
                vf = verify.merkle_proof.verify_merkle_proof(t_hash, t_siblings, root)
                if rt != expected_verified or vf != expected_verified:
                    problems.append(f"tampered leaf verified runtime={rt} verify={vf}, expected {expected_verified}")
            except (KeyError, TypeError, ValueError) as exc:
                problems.append(f"tampered block malformed: {exc}")

        if problems:
            findings.append(Finding("vector", STATUS_FAIL, subject, "; ".join(problems)))
        else:
            findings.append(
                Finding(
                    "vector",
                    STATUS_OK,
                    subject,
                    f"{len(leaf_bytes)} leaf/leaves, root {root.hex()[:12]}, runtime + wakir_verify agree"
                    + (", tampered case rejected" if tampered is not None else ""),
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Level: manifest (+ version pin) and proof format
# ---------------------------------------------------------------------------


def locate_demo_artifacts(demo_workdir: Path) -> tuple[Optional[Path], Optional[Path], list[Finding]]:
    findings: list[Finding] = []
    proof_path = demo_workdir / "proof.json"
    manifests = sorted(demo_workdir.glob("*/manifest.json"))
    if not proof_path.is_file():
        findings.append(Finding("proof", STATUS_FAIL, "proof.json", f"not found in {demo_workdir}"))
        proof_path = None
    if len(manifests) != 1:
        findings.append(Finding("manifest", STATUS_FAIL, "manifest.json", f"expected exactly one <hour>/manifest.json in {demo_workdir}, found {len(manifests)}"))
        return proof_path, None, findings
    return proof_path, manifests[0], findings


def check_manifest(
    runtime_root: Path,
    protocol_root: Path,
    demo_workdir: Path,
    manifest_path: Path,
    proof_path: Optional[Path],
    aggregator_cli: Any,
    verify_cli: Any,
    verify: VerifyModules,
) -> list[Finding]:
    findings: list[Finding] = []
    raw = canon.load_json(manifest_path)
    manifest_version = aggregator_cli.MANIFEST_VERSION

    # -- version pin: constant ↔ manifest ↔ protocol schema ($id + enum)
    if raw.get("version") != manifest_version:
        findings.append(Finding("manifest", STATUS_FAIL, "version", f"manifest version {raw.get('version')!r} ≠ MANIFEST_VERSION {manifest_version!r}"))
    schema_path = protocol_root / PROTOCOL_SCHEMA_DIR / MANIFEST_SCHEMA_FILE
    if not schema_path.exists():
        findings.append(Finding("manifest", STATUS_FAIL, MANIFEST_SCHEMA_FILE, "protocol manifest schema missing"))
    else:
        schema = canon.load_json(schema_path)
        slug = manifest_version.replace("/", "-")
        schema_id = str(schema.get("$id", ""))
        if slug not in schema_id:
            findings.append(Finding("manifest", STATUS_FAIL, "version", f"MANIFEST_VERSION slug {slug!r} not in protocol schema $id {schema_id!r}"))
        enum = ((schema.get("properties") or {}).get("version") or {}).get("enum")
        if isinstance(enum, list) and manifest_version not in enum:
            findings.append(Finding("manifest", STATUS_FAIL, "version", f"MANIFEST_VERSION {manifest_version!r} not accepted by protocol schema enum {enum!r}"))
        errors = validate_instance(schema, raw)
        if errors:
            findings.append(Finding("manifest", STATUS_FAIL, "manifest.json", "violates protocol manifest schema: " + "; ".join(errors[:3])))
        else:
            findings.append(Finding("manifest", STATUS_OK, "manifest.json", f"validates against protocol {MANIFEST_SCHEMA_FILE}; version {manifest_version} pinned in $id + enum"))

    # -- wakir-verify loader roundtrip
    try:
        loaded = verify.manifest.load_manifest_from_file(manifest_path)
    except Exception as exc:  # noqa: BLE001 - surfaced as a finding
        findings.append(Finding("manifest", STATUS_FAIL, "wakir_verify.manifest", f"loader rejected runtime manifest: {exc}"))
        return findings

    problems: list[str] = []
    if loaded.merkle_root.hex() != raw.get("merkle_root"):
        problems.append("loader root ≠ recorded merkle_root")
    if not verify.manifest.compute_manifest_consistency(loaded):
        problems.append("wakir_verify re-derived root ≠ recorded merkle_root")
    if len(loaded.leaves) != raw.get("event_count"):
        problems.append(f"loader saw {len(loaded.leaves)} leaves, manifest says event_count={raw.get('event_count')}")
    # Constraint C1 — pinned divergence.
    if loaded.envelope != str(raw.get("envelope", "")):
        problems.append("C1: loader envelope ≠ manifest envelope field")
    if "envelope" in raw and raw["envelope"] != raw.get("version"):
        problems.append("C1: manifest carries `envelope` that differs from `version`")
    if loaded.hour != raw.get("hour"):
        problems.append("C1: loader hour ≠ manifest hour field")
    if "hour" in raw and raw["hour"] != raw.get("hour_slot"):
        problems.append("C1: manifest carries `hour` that differs from `hour_slot`")
    if problems:
        findings.append(Finding("manifest", STATUS_FAIL, "wakir_verify.manifest", "; ".join(problems)))
    else:
        findings.append(Finding("manifest", STATUS_OK, "wakir_verify.manifest", f"roundtrip ok; constraint C1 pinned ({CONSTRAINT_C1})"))

    # -- runtime verify CLI reproduces the emitted sibling path
    if proof_path is not None and proof_path.is_file():
        proof = canon.load_json(proof_path)
        try:
            leaf, all_leaves = verify_cli.lookup_event_in_hour(proof["event_id"], raw["hour_slot"], demo_workdir)
            rebuilt = verify_cli.reconstruct_proof_from_leaves(leaf, all_leaves)
        except Exception as exc:  # noqa: BLE001
            findings.append(Finding("manifest", STATUS_FAIL, "wat.verify.cli", f"could not rebuild proof from manifest: {exc}"))
            return findings
        cli_problems: list[str] = []
        if leaf.hex() != proof.get("leaf_hash"):
            cli_problems.append("CLI leaf hash ≠ proof.json leaf_hash")
        if list(rebuilt) != _siblings_from_doc(proof):
            cli_problems.append("CLI sibling path ≠ proof.json siblings")
        if not verify.merkle_proof.verify_merkle_proof(leaf, rebuilt, loaded.merkle_root):
            cli_problems.append("wakir_verify rejects CLI-rebuilt proof")
        if cli_problems:
            findings.append(Finding("manifest", STATUS_FAIL, "wat.verify.cli", "; ".join(cli_problems)))
        else:
            findings.append(Finding("manifest", STATUS_OK, "wat.verify.cli", "rebuilt sibling path equals proof.json; accepted by wakir_verify"))
    return findings


def check_proof_format(
    proof_path: Path,
    manifest_path: Optional[Path],
    proof_choice: Optional[ProofSchemaChoice],
    verify: VerifyModules,
) -> list[Finding]:
    findings: list[Finding] = []
    try:
        proof = canon.load_json(proof_path)
    except (OSError, ValueError) as exc:
        return [Finding("proof", STATUS_FAIL, "proof.json", f"unreadable: {exc}")]

    if proof.get("schema") != PROOF_SCHEMA_ID:
        findings.append(Finding("proof", STATUS_FAIL, "proof.json", f"schema field {proof.get('schema')!r} ≠ {PROOF_SCHEMA_ID!r}"))
    if proof_choice is not None:
        findings.extend(validate_proof_document(proof_choice, proof, "proof.json"))

    if manifest_path is not None and manifest_path.is_file():
        raw = canon.load_json(manifest_path)
        problems: list[str] = []
        if proof.get("merkle_root") != raw.get("merkle_root"):
            problems.append("proof merkle_root ≠ manifest merkle_root")
        if proof.get("leaf_count") != raw.get("event_count"):
            problems.append("proof leaf_count ≠ manifest event_count")
        if proof.get("manifest_version") != raw.get("version"):
            problems.append("proof manifest_version ≠ manifest version")
        if proof.get("hour") != raw.get("hour_slot"):
            problems.append("proof hour ≠ manifest hour_slot")
        try:
            ok = verify.merkle_proof.verify_merkle_proof(
                bytes.fromhex(proof["leaf_hash"]),
                _siblings_from_doc(proof),
                bytes.fromhex(raw["merkle_root"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            ok = False
            problems.append(f"proof not verifiable: {exc}")
        if not ok:
            problems.append("wakir_verify.verify_merkle_proof → False")
        if problems:
            findings.append(Finding("proof", STATUS_FAIL, "proof.json↔manifest", "; ".join(problems)))
        else:
            findings.append(Finding("proof", STATUS_OK, "proof.json↔manifest", "root/count/version/hour consistent; wakir_verify verifies the sibling path"))
    return findings


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def run(
    *,
    runtime_root: Path,
    protocol_root: Path,
    verify_root: Optional[Path],
    demo_workdir: Optional[Path],
    allowlist_path: Path,
    today: Optional[_dt.date] = None,
) -> Report:
    today = today or _dt.date.today()
    report = Report(
        protocol_head=git_head(protocol_root),
        verify_head=git_head(verify_root) if verify_root else "installed",
        runtime_head=git_head(runtime_root),
    )

    # -- setup
    if not protocol_root.is_dir():
        report.add("setup", STATUS_FAIL, "protocol", f"checkout missing: {protocol_root}")
        return report
    if _jsonschema() is None:
        report.add("setup", STATUS_FAIL, "jsonschema", "python package `jsonschema` is required")
        return report
    try:
        verify = import_verify(verify_root)
    except ImportError as exc:
        report.add("setup", STATUS_FAIL, "wakir_verify", f"not importable: {exc}")
        return report
    if verify_root is not None and not verify.location.startswith(str(verify_root.resolve())):
        report.add("setup", STATUS_WARN, "wakir_verify", f"imported from {verify.location}, not from {verify_root}")
    try:
        aggregator, aggregator_cli, verify_cli = import_runtime(runtime_root)
    except ImportError as exc:
        report.add("setup", STATUS_FAIL, "wat", f"runtime modules not importable: {exc}")
        return report
    report.add("setup", STATUS_OK, "imports", f"wakir_verify from {verify.location}")

    # -- allowlist
    try:
        entries = allowlist_mod.load_allowlist(allowlist_path)
    except allowlist_mod.AllowlistError as exc:
        report.add("allowlist", STATUS_FAIL, allowlist_path.name, str(exc))
        entries = []
    for expired in allowlist_mod.expired_entries(entries, today):
        report.add("allowlist", STATUS_FAIL, expired.path, f"allowlist entry expired on {expired.until} ({expired.tracking})")
    active = allowlist_mod.active_index(entries, today)
    used: set[str] = set()

    # -- levels
    proof_choice, choice_findings = select_proof_schema(runtime_root, protocol_root)
    report.proof_schema_source = proof_choice.source if proof_choice else "unavailable"
    report.extend(check_schemas(runtime_root, protocol_root, active, used))
    report.extend(check_vectors(protocol_root, aggregator, verify, proof_choice))
    report.extend(choice_findings)

    if demo_workdir is None:
        report.add("manifest", STATUS_FAIL, "demo-workdir", "no --demo-workdir given; manifest + proof levels require `make demo-proof` output")
    else:
        proof_path, manifest_path, locate_findings = locate_demo_artifacts(demo_workdir)
        report.extend(locate_findings)
        if manifest_path is not None:
            report.extend(
                check_manifest(
                    runtime_root, protocol_root, demo_workdir, manifest_path, proof_path,
                    aggregator_cli, verify_cli, verify,
                )
            )
        if proof_path is not None:
            report.extend(check_proof_format(proof_path, manifest_path, proof_choice, verify))

    for path, entry in active.items():
        if path not in used:
            report.add("allowlist", STATUS_WARN, path, f"unused allowlist entry (until {entry.until}); remove it")
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--runtime", type=Path, default=REPO_ROOT_DEFAULT, help="wakir-runtime checkout (default: this repo)")
    parser.add_argument("--protocol", type=Path, required=True, help="wakir-protocol checkout")
    parser.add_argument("--verify", type=Path, default=None, help="wakir-verify checkout (default: whatever is installed)")
    parser.add_argument("--demo-workdir", type=Path, default=None, help="DEMO_PROOF_WORKDIR of a completed `make demo-proof`")
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST_DEFAULT)
    parser.add_argument("--today", type=_dt.date.fromisoformat, default=None, help="override today's date (tests)")
    parser.add_argument("--summary-md", type=Path, default=None, help="write a markdown summary here")
    parser.add_argument("--report-json", type=Path, default=None, help="write the JSON report here")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    report = run(
        runtime_root=args.runtime.resolve(),
        protocol_root=args.protocol.resolve(),
        verify_root=args.verify.resolve() if args.verify else None,
        demo_workdir=args.demo_workdir.resolve() if args.demo_workdir else None,
        allowlist_path=args.allowlist,
        today=args.today,
    )
    print(report.render_text())
    if args.summary_md:
        args.summary_md.parent.mkdir(parents=True, exist_ok=True)
        args.summary_md.write_text(report.render_markdown(), encoding="utf-8")
    if args.report_json:
        args.report_json.parent.mkdir(parents=True, exist_ok=True)
        args.report_json.write_text(json.dumps(report.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 1 if report.has_fail() else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
