#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Tag-78 Engine-Migration-Drift Audit (Selin, persona-engine).
============================================================

Purpose
-------
Verify the migration-consistency between the **Python Stage-1
authority** (``wirelang/persona_engine/welle_state_producer.py``,
``engine.py``, ``engine_async.py`` and their adjacent authority
modules) and the **Rust Stage-2 plan substrate** (the
``wirelang-rust/crates/persona-engine-*`` workspace members).

The Phase-3c-Welle-Marathon is in its closeout window
(Tag-77 Marathon-Final-Smoke PR #489 merged). The post-cutover
sequence calls for the Rust Stage-2 plan substrate to progressively
absorb the Python authority surface. Before the cutover-anchor flips,
operators need a **read-only drift map**: which Python authority
symbols already have a declared Rust pendant, which do not yet, and
where the Rust pendant declares a Python parity-anchor that no longer
resolves (i.e. a stale or renamed authority).

This helper is **audit-only**. It performs no migration step. It
neither modifies Python nor Rust sources, neither schedules a
cutover, nor proposes a parity-anchor relocation. The output is a
JSON drift-envelope intended for Operator-Hand triage in the Tag-78
Marathon-Polish-Phase.

Drift dimensions
----------------
The audit walks four orthogonal drift dimensions:

  D1. *Python-authority-symbol coverage* — for each catalogued
      Python authority module, enumerate the canonical symbol set
      (top-level ``STATUS_*`` / ``*_MARKER_*`` / ``*_GUARDED_WELLEN``
      / ``ALLOWED_TRANSITIONS`` / ``VALID_WELLE_NUMBERS`` constants
      and ``handle_welle_*`` / ``handle_*_event`` function names),
      and record whether the module is present on the runtime tip.

  D2. *Rust-crate parity-anchor declaration* — for each
      ``persona-engine-*`` Rust crate in the workspace, scan the
      crate's ``src/lib.rs`` header for explicit Python-authority
      anchor declarations (substrings of the form
      ``wirelang/persona_engine/<name>.py`` or
      ``wirelang.persona_engine.<name>``).

  D3. *Cross-side drift classification* — for each Python authority
      module, classify whether (a) any Rust crate declares it as a
      parity-anchor (``rust-pendant-present``), or (b) no Rust crate
      declares it (``rust-pendant-absent``), or (c) the Rust crate
      that declares it cannot be found on disk (``stale-anchor``,
      defensive case).

  D4. *Welle-state-machine drift* — the Welle-state-machine
      (``welle_state_producer.py``: STATUS_PENDING, STATUS_IN_PROGRESS,
      STATUS_SIGNED_OFF, STATUS_ROLLED_BACK + ALLOWED_TRANSITIONS) is
      the Stage-1-authority for the Phase-3c-Welle-Marathon. The
      audit records whether any Rust crate declares it as parity-
      anchor. Tag-78 expectation: ``rust-pendant-absent`` (no
      ``persona-engine-welle-state-producer`` crate exists). This is
      **not a regression**; it is the post-cutover migration map.

Output contract
---------------
``run_audit(...)`` returns a :class:`DriftEnvelope` that serialises
to a stable JSON shape via :meth:`DriftEnvelope.to_json`. Top-level
keys::

  {
    "audit_id":           "tag-78-engine-migration-drift-audit",
    "audit_only":         true,
    "runtime_root":       "<absolute path>",
    "python_authorities": [ { module-report, ... } ],
    "rust_crates":        [ { crate-report, ... } ],
    "drift_map":          [ { authority-module x rust-pendant, ... } ],
    "welle_state_machine_drift": { ... },
    "summary": {
      "python_authorities_total":     N,
      "python_authorities_present":   N,
      "rust_crates_total":            N,
      "rust_crates_with_anchor":      N,
      "authorities_with_pendant":     N,
      "authorities_without_pendant":  N,
      "stale_anchor_count":           N,
      "welle_state_pendant_present":  bool
    }
  }

Per-Python-authority module-report::

  {
    "module": "wirelang/persona_engine/welle_state_producer.py",
    "present": true,
    "symbol_kinds": {
      "status_constants":           N,
      "marker_literals":            N,
      "guarded_welle_sets":         N,
      "transition_tables":          N,
      "valid_welle_numbers":        N,
      "handler_functions":          N,
      "error_classes":              N
    },
    "symbol_total": N
  }

Per-Rust-crate crate-report::

  {
    "crate":          "persona-engine-fsm",
    "lib_rs_present": true,
    "declared_python_anchors": [
      "wirelang/persona_engine/lifecycle_state_machine.py", ...
    ],
    "declared_anchor_count": N
  }

Per-drift_map entry::

  {
    "python_authority":  "wirelang/persona_engine/<name>.py",
    "rust_pendants":     ["persona-engine-<crate>", ...],
    "drift_class":       "rust-pendant-present"
                         | "rust-pendant-absent"
                         | "stale-anchor"
  }

Scope discipline
----------------
- **Audit-only.** No file is written by this module except the
  optional ``--out`` JSON envelope at the CLI layer. No Python
  source is modified. No Rust source is modified. No git operation
  is invoked.
- **Pure stdlib.** No third-party dependency. No network. No
  subprocess. No JSON-schema validator import.
- **Hermetic-test-friendly.** All file I/O takes explicit path
  parameters; the test suite passes ``tmp_path`` fixtures and
  manufactures the authority/crate skeleton in isolation.
- **Domain-respect (Selin).** This audit does NOT propose any
  Python or Rust code change. It does NOT touch persona-definition
  files (Aisha-Domaene), WAT-core (Tomas), identity-substrate (Reza),
  or container-infra (Kai).

Tag-78, Selin-Hand, AI-Corp Continuous-Mode.
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import re
from typing import Iterable, Tuple


AUDIT_ID = "tag-78-engine-migration-drift-audit"


# ---------------------------------------------------------------- #
# Python authority catalogue                                       #
# ---------------------------------------------------------------- #
#
# The Tag-78 audit pins the *catalogue* of Python authority modules
# that the Phase-3c-Welle-Marathon engine substrate depends on. The
# catalogue is intentionally hard-coded: it is the cross-side
# migration-map contract that the Tag-78 polish-layer pins. New
# Python authorities (e.g. Tag-78+ additions) must be added here in
# lockstep with the parity-anchor declaration on the Rust side.
#
# The path is relative to the runtime-root (typically the
# ``wakir-runtime`` repo tip).

PYTHON_AUTHORITY_MODULES: Tuple[str, ...] = (
    # Engine substrate (Stage-1 authority).
    "wirelang/persona_engine/welle_state_producer.py",
    "wirelang/persona_engine/engine.py",
    "wirelang/persona_engine/engine_async.py",
    # Lifecycle FSM + canonical sibling.
    "wirelang/persona_engine/lifecycle_state_machine.py",
    "wirelang/persona_engine/lifecycle_state_machine_canonical.py",
    # State-backing.
    "wirelang/persona_engine/state_backing.py",
    # Recovery + canonical sibling.
    "wirelang/persona_engine/recovery_workflow.py",
    "wirelang/persona_engine/recovery_workflow_canonical.py",
    # V-907 hash-pin + canonical sibling.
    "wirelang/persona_engine/v907_verify.py",
    "wirelang/persona_engine/v907_verify_canonical.py",
    # Bridge audit substrate + canonical siblings.
    "wirelang/persona_engine/bridge_audit_diff_engine.py",
    "wirelang/persona_engine/bridge_audit_diff_engine_canonical.py",
    "wirelang/persona_engine/bridge_audit_writer.py",
    "wirelang/persona_engine/bridge_audit_replay_canonical.py",
    # NATS substrate (subjects + subscribe-loop + ack).
    "wirelang/persona_engine/nats_subjects.py",
    "wirelang/persona_engine/nats_subscribe_loop.py",
    # Anchor + SVID + migration.
    "wirelang/persona_engine/anchor_emitter.py",
    "wirelang/persona_engine/svid_workload_identity.py",
    "wirelang/persona_engine/migrate_version.py",
    "wirelang/persona_engine/migrate_version_canonical.py",
)


# Python authority modules whose Rust pendant is *expected absent*
# at Tag-78 (the welle-state-producer is the Stage-1-only authority
# for the Phase-3c Marathon; no Rust pendant has been spawned yet).
# Modules in this set are NOT counted as drift even if no Rust
# anchor is declared. The set is used for verdict-classification
# only; the drift_map entry still carries the ``rust-pendant-absent``
# class so the report stays honest about the absence.
WELLE_STATE_AUTHORITIES_RUST_PENDANT_EXPECTED_ABSENT: frozenset[str] = frozenset({
    "wirelang/persona_engine/welle_state_producer.py",
    "wirelang/persona_engine/engine.py",
    "wirelang/persona_engine/engine_async.py",
})


# Symbol-kind regex catalogue. Each regex matches a top-level
# Python construct that the cross-side migration map cares about.
# All regexes are intentionally line-anchored (``^`` + MULTILINE) to
# avoid catching nested / commented-out occurrences inside docstrings.
_SYMBOL_KIND_PATTERNS = {
    "status_constants":     re.compile(r"^STATUS_[A-Z_]+\s*=", re.MULTILINE),
    "marker_literals":      re.compile(
        r"^(?:DOPPELBETRIEB_[A-Z_]+|SNAPSHOT_[A-Z_]+|CAPABILITY_TOKEN_[A-Z_]+|"
        r"CROSS_SUBSTRATE_[A-Z_]+|FINAL_SEALING_[A-Z_]+|ROLLBACK_MARKER_[A-Z_]+|"
        r"PHASE_3_COMPLETE_[A-Z_]+)\s*=",
        re.MULTILINE,
    ),
    "guarded_welle_sets":   re.compile(r"^[A-Z_]+_GUARDED_WELLEN\s*=", re.MULTILINE),
    "transition_tables":    re.compile(r"^(?:ALLOWED_TRANSITIONS|VALID_TRANSITIONS)\s*=", re.MULTILINE),
    "valid_welle_numbers":  re.compile(r"^VALID_WELLE_NUMBERS\s*=", re.MULTILINE),
    "handler_functions":    re.compile(r"^def\s+handle_[a-z0-9_]+_event\s*\(", re.MULTILINE),
    "error_classes":        re.compile(r"^class\s+[A-Za-z0-9_]+Error\s*\(", re.MULTILINE),
}


# ---------------------------------------------------------------- #
# Rust-crate parity-anchor extraction                              #
# ---------------------------------------------------------------- #
#
# The Rust workspace lives at ``wirelang-rust/crates/`` relative to
# the runtime-root. The audit walks every ``persona-engine-*``
# directory that contains a ``src/lib.rs`` and extracts the set of
# Python authority anchors declared in the file header. Anchors
# are recognised in two forms:
#
#   - path form:   ``wirelang/persona_engine/<name>.py``
#   - module form: ``wirelang.persona_engine.<name>`` (with optional
#                  ``.<submodule>`` suffix; the suffix is stripped to
#                  match the path-form authority list)
#
# Only the ``persona-engine-*`` crates (workspace member prefix) are
# scanned. The ``persona-hash`` / ``persona-canonical-form`` family
# crates belong to a different migration anchor (V-907 hash pin)
# and are deliberately out-of-scope for the Welle-Marathon drift map.

RUST_CRATES_DIR = "wirelang-rust/crates"
RUST_CRATE_PREFIX = "persona-engine-"

_ANCHOR_PATH_RE = re.compile(
    r"`?(wirelang/persona_engine/[A-Za-z0-9_]+\.py)`?"
)
_ANCHOR_MODULE_RE = re.compile(
    r"`?(wirelang\.persona_engine\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)`?"
)


def _module_to_path(module: str) -> str:
    """
    Convert a ``wirelang.persona_engine.<name>`` Rust-comment anchor
    to the canonical authority-list path form
    ``wirelang/persona_engine/<name>.py``.

    The ``<name>`` segment is taken as the **first** component after
    ``persona_engine``; any further ``.<submodule>`` suffix is stripped
    (the cross-side authority anchor lives at module-file granularity,
    not symbol granularity).
    """
    parts = module.split(".")
    # parts[0] == "wirelang", parts[1] == "persona_engine"
    if len(parts) < 3:
        return ""
    return f"wirelang/persona_engine/{parts[2]}.py"


# ---------------------------------------------------------------- #
# Dataclasses                                                      #
# ---------------------------------------------------------------- #


@dataclasses.dataclass(frozen=True)
class SymbolKinds:
    status_constants: int
    marker_literals: int
    guarded_welle_sets: int
    transition_tables: int
    valid_welle_numbers: int
    handler_functions: int
    error_classes: int

    @property
    def total(self) -> int:
        return (
            self.status_constants
            + self.marker_literals
            + self.guarded_welle_sets
            + self.transition_tables
            + self.valid_welle_numbers
            + self.handler_functions
            + self.error_classes
        )


@dataclasses.dataclass(frozen=True)
class PythonAuthorityReport:
    module: str
    present: bool
    symbol_kinds: SymbolKinds
    symbol_total: int


@dataclasses.dataclass(frozen=True)
class RustCrateReport:
    crate: str
    lib_rs_present: bool
    declared_python_anchors: Tuple[str, ...]
    declared_anchor_count: int


@dataclasses.dataclass(frozen=True)
class DriftMapEntry:
    python_authority: str
    rust_pendants: Tuple[str, ...]
    drift_class: str  # "rust-pendant-present" | "rust-pendant-absent" | "stale-anchor"


@dataclasses.dataclass(frozen=True)
class WelleStateMachineDrift:
    """
    Tag-78 D4 dimension report. The Welle-state-machine (status +
    transitions + guarded-welle-sets + marker-literals) lives only on
    the Python side at Tag-78. This block surfaces the salient
    properties of that asymmetry as a stable, easy-to-cite shape.
    """

    python_authority: str
    python_authority_present: bool
    python_status_constants: int
    python_marker_literals: int
    python_guarded_welle_sets: int
    python_transition_tables: int
    rust_pendant_declared: bool
    rust_pendant_crate: str | None
    expected_absent: bool
    drift_class: str  # "rust-pendant-present" | "rust-pendant-absent-expected" | "rust-pendant-absent-drift"


@dataclasses.dataclass(frozen=True)
class Summary:
    python_authorities_total: int
    python_authorities_present: int
    rust_crates_total: int
    rust_crates_with_anchor: int
    authorities_with_pendant: int
    authorities_without_pendant: int
    stale_anchor_count: int
    welle_state_pendant_present: bool


@dataclasses.dataclass(frozen=True)
class DriftEnvelope:
    audit_id: str
    audit_only: bool
    runtime_root: str
    python_authorities: Tuple[PythonAuthorityReport, ...]
    rust_crates: Tuple[RustCrateReport, ...]
    drift_map: Tuple[DriftMapEntry, ...]
    welle_state_machine_drift: WelleStateMachineDrift
    summary: Summary

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(dataclasses.asdict(self), indent=indent, sort_keys=False)


# ---------------------------------------------------------------- #
# Authority-side scanner                                           #
# ---------------------------------------------------------------- #


def _count_kind(text: str, pattern: re.Pattern[str]) -> int:
    return sum(1 for _ in pattern.finditer(text))


def scan_python_authority(module_path: pathlib.Path) -> SymbolKinds:
    """
    Read ``module_path`` and return the :class:`SymbolKinds` count
    by kind. If the file does not exist, returns a zero-filled
    :class:`SymbolKinds`. Pure stdlib; no AST parser.

    The scanner is *substring-counting-by-regex* by design: it does
    not import the Python module (the welle_state_producer pulls in
    its own dependency tree and importing it under audit would
    couple the audit to runtime state). The regex catalogue is
    line-anchored so it does not catch docstring / comment mentions.
    """
    if not module_path.exists():
        return SymbolKinds(0, 0, 0, 0, 0, 0, 0)
    text = module_path.read_text(encoding="utf-8")
    return SymbolKinds(
        status_constants=_count_kind(text, _SYMBOL_KIND_PATTERNS["status_constants"]),
        marker_literals=_count_kind(text, _SYMBOL_KIND_PATTERNS["marker_literals"]),
        guarded_welle_sets=_count_kind(text, _SYMBOL_KIND_PATTERNS["guarded_welle_sets"]),
        transition_tables=_count_kind(text, _SYMBOL_KIND_PATTERNS["transition_tables"]),
        valid_welle_numbers=_count_kind(text, _SYMBOL_KIND_PATTERNS["valid_welle_numbers"]),
        handler_functions=_count_kind(text, _SYMBOL_KIND_PATTERNS["handler_functions"]),
        error_classes=_count_kind(text, _SYMBOL_KIND_PATTERNS["error_classes"]),
    )


# ---------------------------------------------------------------- #
# Rust-side scanner                                                #
# ---------------------------------------------------------------- #


def extract_python_anchors_from_rust(lib_rs_text: str) -> Tuple[str, ...]:
    """
    Extract the set of declared Python authority anchors from a Rust
    ``lib.rs`` source. Recognises both path-form
    (``wirelang/persona_engine/<name>.py``) and module-form
    (``wirelang.persona_engine.<name>[.suffix]``) anchors. Returns a
    sorted-unique tuple of path-form strings.
    """
    paths: set[str] = set()
    for m in _ANCHOR_PATH_RE.finditer(lib_rs_text):
        paths.add(m.group(1))
    for m in _ANCHOR_MODULE_RE.finditer(lib_rs_text):
        p = _module_to_path(m.group(1))
        if p:
            paths.add(p)
    return tuple(sorted(paths))


def list_persona_engine_crates(workspace_root: pathlib.Path) -> Tuple[str, ...]:
    """
    Enumerate ``persona-engine-*`` directories under
    ``<workspace_root>/wirelang-rust/crates/``. Returns a sorted
    tuple of crate names (basename only). Pure-stdlib directory
    walk; does not parse Cargo.toml.
    """
    crates_dir = workspace_root / RUST_CRATES_DIR
    if not crates_dir.exists() or not crates_dir.is_dir():
        return ()
    crates: list[str] = []
    for child in crates_dir.iterdir():
        if not child.is_dir():
            continue
        if not child.name.startswith(RUST_CRATE_PREFIX):
            continue
        crates.append(child.name)
    return tuple(sorted(crates))


def scan_rust_crate(crate_dir: pathlib.Path) -> RustCrateReport:
    """
    Scan a single Rust crate directory and produce a
    :class:`RustCrateReport`. The scanner reads only
    ``<crate_dir>/src/lib.rs`` and extracts declared Python authority
    anchors via :func:`extract_python_anchors_from_rust`.
    """
    crate_name = crate_dir.name
    lib_rs = crate_dir / "src" / "lib.rs"
    if not lib_rs.exists():
        return RustCrateReport(
            crate=crate_name,
            lib_rs_present=False,
            declared_python_anchors=(),
            declared_anchor_count=0,
        )
    text = lib_rs.read_text(encoding="utf-8")
    anchors = extract_python_anchors_from_rust(text)
    return RustCrateReport(
        crate=crate_name,
        lib_rs_present=True,
        declared_python_anchors=anchors,
        declared_anchor_count=len(anchors),
    )


# ---------------------------------------------------------------- #
# Cross-side drift classification                                  #
# ---------------------------------------------------------------- #


def classify_drift(
    *,
    python_authorities: Iterable[PythonAuthorityReport],
    rust_crates: Iterable[RustCrateReport],
) -> Tuple[DriftMapEntry, ...]:
    """
    For each Python authority module, determine which (if any) Rust
    crates declare it as a parity-anchor, and emit a
    :class:`DriftMapEntry` per authority module.

    Classification rules (mirrors the docstring D3 dimension):

      - ``rust-pendant-present`` if at least one Rust crate declares
        the authority and the Python authority itself is present.
      - ``rust-pendant-absent`` if the Python authority is present
        and no Rust crate declares it.
      - ``stale-anchor`` if a Rust crate declares the authority but
        the Python authority file does not exist on disk (defensive
        case; would indicate a renamed-but-not-followed authority).
    """
    auth_index = {a.module: a for a in python_authorities}
    # Map Rust crates -> declared anchors (path form).
    anchor_to_crates: dict[str, list[str]] = {}
    for c in rust_crates:
        for a in c.declared_python_anchors:
            anchor_to_crates.setdefault(a, []).append(c.crate)

    entries: list[DriftMapEntry] = []
    seen_authorities: set[str] = set()

    for auth in python_authorities:
        seen_authorities.add(auth.module)
        pendants = tuple(sorted(anchor_to_crates.get(auth.module, [])))
        if pendants:
            drift_class = "rust-pendant-present"
        else:
            drift_class = "rust-pendant-absent"
        entries.append(
            DriftMapEntry(
                python_authority=auth.module,
                rust_pendants=pendants,
                drift_class=drift_class,
            )
        )

    # Stale anchors: Rust declares an anchor that is not in the
    # authority catalogue OR the catalogue entry is not present on
    # disk.
    for anchor, crates in sorted(anchor_to_crates.items()):
        if anchor in seen_authorities:
            auth = auth_index.get(anchor)
            if auth is not None and not auth.present:
                # Rewrite the entry to ``stale-anchor``.
                for i, e in enumerate(entries):
                    if e.python_authority == anchor:
                        entries[i] = DriftMapEntry(
                            python_authority=anchor,
                            rust_pendants=tuple(sorted(crates)),
                            drift_class="stale-anchor",
                        )
                        break
            continue
        # Rust references an anchor not in our catalogue -> stale.
        entries.append(
            DriftMapEntry(
                python_authority=anchor,
                rust_pendants=tuple(sorted(crates)),
                drift_class="stale-anchor",
            )
        )

    # Stable order: keep the catalogue order for catalogued entries,
    # then append stale-anchor extras sorted by name.
    catalogued = [e for e in entries if e.python_authority in seen_authorities]
    extras = sorted(
        [e for e in entries if e.python_authority not in seen_authorities],
        key=lambda e: e.python_authority,
    )
    return tuple(catalogued + extras)


# ---------------------------------------------------------------- #
# Welle-state-machine drift block                                  #
# ---------------------------------------------------------------- #


WELLE_STATE_AUTHORITY_PATH = "wirelang/persona_engine/welle_state_producer.py"


def compute_welle_state_machine_drift(
    *,
    python_authorities: Iterable[PythonAuthorityReport],
    drift_map: Iterable[DriftMapEntry],
) -> WelleStateMachineDrift:
    """
    Compose the D4 Welle-state-machine drift block. Looks up the
    welle_state_producer authority and its (possibly empty) Rust
    pendant set, and resolves the drift-class. Tag-78 expectation:
    ``rust-pendant-absent-expected`` (the welle_state_producer has
    no Rust pendant by design; that is the Stage-2 plan gap).
    """
    auth = next(
        (a for a in python_authorities if a.module == WELLE_STATE_AUTHORITY_PATH),
        None,
    )
    entry = next(
        (e for e in drift_map if e.python_authority == WELLE_STATE_AUTHORITY_PATH),
        None,
    )
    pendants = entry.rust_pendants if entry is not None else ()
    pendant_declared = len(pendants) > 0
    expected_absent = WELLE_STATE_AUTHORITY_PATH in WELLE_STATE_AUTHORITIES_RUST_PENDANT_EXPECTED_ABSENT

    if pendant_declared:
        drift_class = "rust-pendant-present"
    elif expected_absent:
        drift_class = "rust-pendant-absent-expected"
    else:
        drift_class = "rust-pendant-absent-drift"

    if auth is None:
        return WelleStateMachineDrift(
            python_authority=WELLE_STATE_AUTHORITY_PATH,
            python_authority_present=False,
            python_status_constants=0,
            python_marker_literals=0,
            python_guarded_welle_sets=0,
            python_transition_tables=0,
            rust_pendant_declared=False,
            rust_pendant_crate=None,
            expected_absent=expected_absent,
            drift_class="rust-pendant-absent-expected" if expected_absent else "rust-pendant-absent-drift",
        )

    return WelleStateMachineDrift(
        python_authority=WELLE_STATE_AUTHORITY_PATH,
        python_authority_present=auth.present,
        python_status_constants=auth.symbol_kinds.status_constants,
        python_marker_literals=auth.symbol_kinds.marker_literals,
        python_guarded_welle_sets=auth.symbol_kinds.guarded_welle_sets,
        python_transition_tables=auth.symbol_kinds.transition_tables,
        rust_pendant_declared=pendant_declared,
        rust_pendant_crate=pendants[0] if pendant_declared else None,
        expected_absent=expected_absent,
        drift_class=drift_class,
    )


# ---------------------------------------------------------------- #
# Public entry-point                                               #
# ---------------------------------------------------------------- #


def run_audit(*, runtime_root: pathlib.Path) -> DriftEnvelope:
    """
    Execute the Tag-78 Engine-Migration-Drift audit against the
    given ``runtime_root`` (the wakir-runtime repo tip). Pure
    function: no side-effects beyond file reads.
    """
    runtime_root = pathlib.Path(runtime_root)

    # D1. Python-authority scan.
    python_authorities: list[PythonAuthorityReport] = []
    for module_rel in PYTHON_AUTHORITY_MODULES:
        module_path = runtime_root / module_rel
        present = module_path.exists()
        kinds = scan_python_authority(module_path)
        python_authorities.append(
            PythonAuthorityReport(
                module=module_rel,
                present=present,
                symbol_kinds=kinds,
                symbol_total=kinds.total,
            )
        )

    # D2. Rust-crate scan.
    crates_dir = runtime_root / RUST_CRATES_DIR
    rust_crates: list[RustCrateReport] = []
    for crate_name in list_persona_engine_crates(runtime_root):
        rust_crates.append(scan_rust_crate(crates_dir / crate_name))

    # D3. Cross-side drift classification.
    drift_map = classify_drift(
        python_authorities=python_authorities,
        rust_crates=rust_crates,
    )

    # D4. Welle-state-machine drift block.
    welle_drift = compute_welle_state_machine_drift(
        python_authorities=python_authorities,
        drift_map=drift_map,
    )

    # Summary.
    summary = Summary(
        python_authorities_total=len(python_authorities),
        python_authorities_present=sum(1 for a in python_authorities if a.present),
        rust_crates_total=len(rust_crates),
        rust_crates_with_anchor=sum(1 for c in rust_crates if c.declared_anchor_count > 0),
        authorities_with_pendant=sum(
            1 for e in drift_map if e.drift_class == "rust-pendant-present"
        ),
        authorities_without_pendant=sum(
            1 for e in drift_map if e.drift_class == "rust-pendant-absent"
        ),
        stale_anchor_count=sum(
            1 for e in drift_map if e.drift_class == "stale-anchor"
        ),
        welle_state_pendant_present=welle_drift.rust_pendant_declared,
    )

    return DriftEnvelope(
        audit_id=AUDIT_ID,
        audit_only=True,
        runtime_root=str(runtime_root.resolve()),
        python_authorities=tuple(python_authorities),
        rust_crates=tuple(rust_crates),
        drift_map=drift_map,
        welle_state_machine_drift=welle_drift,
        summary=summary,
    )


# ---------------------------------------------------------------- #
# CLI                                                              #
# ---------------------------------------------------------------- #


def _default_runtime_root() -> pathlib.Path:
    # Repo-root heuristic: walk up from this file until we find a
    # ``wirelang`` + ``wirelang-rust`` sibling pair.
    here = pathlib.Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "wirelang").is_dir() and (parent / "wirelang-rust").is_dir():
            return parent
    return pathlib.Path.cwd()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="audit_engine_migration_drift",
        description=(
            "Tag-78 Engine-Migration-Drift audit (Python Stage-1 "
            "authority x Rust Stage-2 plan substrate). Audit-only, "
            "pure stdlib."
        ),
    )
    parser.add_argument(
        "--runtime-root",
        type=pathlib.Path,
        default=_default_runtime_root(),
        help=(
            "Path to the wakir-runtime repo root (the directory "
            "containing both ``wirelang/`` and ``wirelang-rust/``). "
            "Default: auto-detected. (%(default)s)"
        ),
    )
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="Optional output JSON file. Default: stdout.",
    )
    args = parser.parse_args(argv)

    envelope = run_audit(runtime_root=args.runtime_root)
    payload = envelope.to_json()

    if args.out is not None:
        args.out.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    # Exit-code contract: 0 if no unexpected drift, 1 if any
    # ``stale-anchor`` entry surfaces (the only audit-only error
    # condition; ``rust-pendant-absent`` is informational and does
    # not flip the exit-code at Tag-78). The welle-state-machine
    # absence is *expected* and does not affect exit-code.
    return 1 if envelope.summary.stale_anchor_count > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
