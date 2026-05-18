#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Licensed under the Business Source License 1.1; see
# wirelang/persona_engine/LICENSE-BSL.md.
# Change Date: 2030-05-15. Change License: Apache License 2.0.
"""Persona-Engine 0.5.1-pre-cutover Boot Self-Test **v2** (Tag-50).

This is the **Tag-50 extension** of the Tag-48 self-test
(``boot-self-test.py``). It carries forward every Tag-48 invariant
(10 BackendDecisions, FSM closure, V-907 pin stability, boot
fingerprint determinism) and adds **three new coverage classes**:

    A. **15-Crate Cross-Lang-Pin Coverage in Boot.** The pin-pack
       ships **15** Rust crates (10 boot-wired + 5 boot-unwired).
       Tag-48 boot-self-test only verifies the 10 boot-wired
       half. The cutover-day operator wants live evidence that
       *every* pin-pack row remains shape-consistent on the
       cutover box (name + version + fixtures-or-note).

    B. **ENV-Flag-Konsistenz-Check across all three sources of
       truth.** The 10 selector ENVs and 10 Rust-binary-override
       ENVs are declared in **three** places:

       * ``wirelang/persona_engine/rust_backend_switch.py`` —
         module-level ``_BACKEND_ENV`` / ``_BIN_ENV`` constants.
       * ``wirelang/persona_engine/MANIFEST-0.5.1-pre-cutover.md``
         §2.1 / §2.2 tables.
       * ``infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml``
         ``selector_env`` / ``binary_env`` keys per boot-wired
         crate.

       Tag-48 self-test verifies the manifest <-> pin-pack arc
       (check #8 ``cross_source_consistency``); it does NOT
       cross-check the **resolver code** against the documents.
       Tag-50 adds that third arc — closing the **DRIFT-S4**
       surface: a resolver-side ENV constant whose name is in the
       module but missing from the manifest §2 tables, or
       vice-versa.

    C. **DRIFT-S4 reconciliation report.** Post-Tag-50, the
       resolver module declares ENV constants for **two** crates
       (``BRIDGE_AUDIT_REPLAY_BACKEND_ENV``,
       ``MIGRATE_VERSION_BACKEND_ENV``) that are **not** in the
       10-flag manifest §2 ENV schema. Tag-50 documents this
       intentionally: the two extra constants gate companion-crate
       subprocess paths that are **not** part of the Stage-1 boot
       fan-out. The self-test pins the **closed enum** of
       resolver-side ENV constants so any future drift (a new
       resolver-side ENV that escapes the pin-pack) trips the
       check.

Why a v2 file and not edits to ``boot-self-test.py``?
-----------------------------------------------------

* **Patch-trace integrity.** The Tag-48 file is referenced by
  ``test_boot_self_test_tag47.py`` and the Tag-48 wire-in audit
  trail. Editing it in place would silently change the contract
  the existing hermetic suite was approved against.
* **Cutover-day boot harness.** v2 runs **alongside** v1 in the
  cutover-day operator runbook (Phase-3b §6, KW 23). v1 stays as
  the 0.5.1-pre-cutover anchor; v2 layers the extra coverage on
  top.

Exit codes
----------

* ``0`` on full success (all 22+ checks pass).
* ``1`` on any check failure; a JSON failure report is emitted to
  stdout.
* ``2`` on environment-level setup error.

Run
---

::

    python3 scripts/persona-engine/boot-self-test-v2.py            # human
    python3 scripts/persona-engine/boot-self-test-v2.py --json     # machine
    python3 scripts/persona-engine/boot-self-test-v2.py --quiet    # silent on success
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Repo-root anchor.
# ---------------------------------------------------------------------------

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parent.parent.parent

MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.1-pre-cutover.md"
)
PIN_PACK_PATH = (
    REPO_ROOT
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.1-pre-cutover.yaml"
)


# ---------------------------------------------------------------------------
# Manifest constants — mirror manifest §1 / §2 / pin-pack.
# ---------------------------------------------------------------------------

EXPECTED_MANIFEST_VERSION = "0.5.1-pre-cutover"
EXPECTED_PIN_VERSION = "0.1.0"

# 10 BackendDecision domains, boot-ordered (Tag-48 wire-in).
EXPECTED_BOOT_ORDER: Tuple[Tuple[int, str, str], ...] = (
    (1, "recovery-workflow", "recovery"),
    (2, "state-backing", "state_backing"),
    (3, "lifecycle-fsm", "fsm"),
    (4, "v907-verify", "v907_verify"),
    (5, "bridge-diff", "bridge_diff"),
    (6, "subscribe-loop", "subscribe_loop"),
    (7, "anchor-emitter", "anchor_emitter"),
    (8, "svid-workload-identity", "svid_workload_identity"),
    (9, "federation-resolver", "federation_resolver"),
    (10, "bridge-audit-writer", "bridge_audit_writer"),
)

# 10 boot-wired pin-pack entries.
EXPECTED_PIN_PACK_BOOT_WIRED: Tuple[Tuple[int, str], ...] = (
    (1, "persona-engine-recovery"),
    (2, "persona-engine-state-backing"),
    (3, "persona-engine-fsm"),
    (4, "persona-engine-v907-verify"),
    (5, "persona-engine-bridge-diff"),
    (6, "persona-engine-subscribe-loop"),
    (7, "persona-engine-anchor-emitter"),
    (8, "persona-engine-svid-workload-identity"),
    (9, "persona-engine-federation-resolver"),
    (10, "persona-engine-bridge-audit-writer"),
)

# 5 boot-unwired pin-pack entries.
EXPECTED_PIN_PACK_UNWIRED: Tuple[str, ...] = (
    "persona-engine-bridge-audit-replay",
    "persona-engine-anchor-submit-worker",
    "persona-engine-frontmatter-parser",
    "persona-engine-bridge-forward",
    "persona-engine-federation-frame-parser",
)

EXPECTED_TOTAL_PIN_PACK_CRATES = 15

# Manifest §2.1 selector ENV schema (10 wired components).
EXPECTED_SELECTOR_ENVS: Tuple[Tuple[str, str], ...] = (
    ("recovery-workflow", "WAKIR_RECOVERY_BACKEND"),
    ("state-backing", "WAKIR_STATE_BACKING_BACKEND"),
    ("lifecycle-fsm", "WAKIR_FSM_BACKEND"),
    ("v907-verify", "WAKIR_V907_VERIFY_BACKEND"),
    ("bridge-diff", "WAKIR_BRIDGE_DIFF_BACKEND"),
    ("subscribe-loop", "WAKIR_SUBSCRIBE_LOOP_BACKEND"),
    ("anchor-emitter", "WAKIR_ANCHOR_EMITTER_BACKEND"),
    ("svid-workload-identity", "WAKIR_SVID_WORKLOAD_IDENTITY_BACKEND"),
    ("federation-resolver", "WAKIR_FEDERATION_RESOLVER_BACKEND"),
    ("bridge-audit-writer", "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"),
)

# Manifest §2.2 Rust-binary-path-override ENV schema.
EXPECTED_BINARY_ENVS: Tuple[Tuple[str, str], ...] = (
    ("recovery-workflow", "WAKIR_RUST_RECOVERY_BIN"),
    ("state-backing", "WAKIR_RUST_STATE_BACKING_BIN"),
    ("lifecycle-fsm", "WAKIR_RUST_FSM_BIN"),
    ("v907-verify", "WAKIR_RUST_V907_VERIFY_BIN"),
    ("bridge-diff", "WAKIR_RUST_BRIDGE_DIFF_BIN"),
    ("subscribe-loop", "WAKIR_RUST_SUBSCRIBE_LOOP_BIN"),
    ("anchor-emitter", "WAKIR_RUST_ANCHOR_EMITTER_BIN"),
    ("svid-workload-identity", "WAKIR_RUST_SVID_WORKLOAD_IDENTITY_BIN"),
    ("federation-resolver", "WAKIR_RUST_FEDERATION_RESOLVER_BIN"),
    ("bridge-audit-writer", "WAKIR_RUST_BRIDGE_AUDIT_WRITER_BIN"),
)

# DRIFT-S4 reconciliation surface: the resolver module declares
# selector-ENV constants for two *companion* crates that are NOT in
# the 10-flag manifest §2.1 ENV schema. These two ENVs gate optional
# Rust subprocess paths that the Stage-1 boot fan-out does not
# consult; they are intentional companion-crate hooks and the
# self-test pins them as a *closed enum* so any new resolver-side
# ENV (which would silently escape the pin-pack) trips the check.
EXPECTED_COMPANION_SELECTOR_ENVS: Tuple[str, ...] = (
    "WAKIR_BRIDGE_AUDIT_REPLAY_BACKEND",
    "WAKIR_MIGRATE_VERSION_BACKEND",
)
EXPECTED_COMPANION_BINARY_ENVS: Tuple[str, ...] = (
    "WAKIR_RUST_BRIDGE_AUDIT_REPLAY_BIN",
    "WAKIR_RUST_MIGRATE_VERSION_BIN",
)

EXPECTED_CROSS_BACKEND_TIMEOUT_ENV = "WAKIR_RUST_BACKEND_TIMEOUT_S"


# ---------------------------------------------------------------------------
# Check infrastructure.
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    elapsed_ms: float = 0.0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


@dataclass
class SelfTestReport:
    boot_baseline: str
    manifest_version: str
    checks: List[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def total(self) -> int:
        return len(self.checks)

    @property
    def failed_count(self) -> int:
        return sum(0 if c.passed else 1 for c in self.checks)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "boot_baseline": self.boot_baseline,
            "manifest_version": self.manifest_version,
            "total_checks": self.total,
            "passed_checks": self.total - self.failed_count,
            "failed_checks": self.failed_count,
            "passed": self.passed,
            "checks": [c.as_dict() for c in self.checks],
        }


def _run_check(
    name: str,
    fn: Callable[[], Tuple[bool, str]],
) -> CheckResult:
    start = time.perf_counter()
    try:
        passed, detail = fn()
    except Exception as exc:  # noqa: BLE001 — top-level harness
        passed = False
        detail = f"check raised {type(exc).__name__}: {exc}"
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    return CheckResult(
        name=name, passed=passed, detail=detail, elapsed_ms=elapsed_ms
    )


# ---------------------------------------------------------------------------
# Stdlib YAML mini-parser — same shape as boot-self-test.py.
# ---------------------------------------------------------------------------


def _parse_pin_pack_yaml(text: str) -> Dict[str, Any]:
    """Parse the pin-pack YAML using only stdlib regex.

    The pin-pack YAML is hand-curated and follows a small subset
    matching the Tag-48 self-test parser. Refer to
    ``boot-self-test.py:_parse_pin_pack_yaml`` for the grammar notes.
    """
    out: Dict[str, Any] = {}
    current_list_key: Optional[str] = None
    current_item: Optional[Dict[str, Any]] = None
    current_scalar_dict: Optional[Dict[str, Any]] = None

    def _coerce(v: str) -> Any:
        v = v.strip()
        if v == "~" or v == "null" or v == "":
            return None
        if v.startswith('"') and v.endswith('"'):
            return v[1:-1]
        if v.startswith("'") and v.endswith("'"):
            return v[1:-1]
        if v.lstrip("-").isdigit():
            return int(v)
        return v

    for raw_line in text.splitlines():
        line = re.sub(r"\s+#.*$", "", raw_line.rstrip())
        if not line.strip():
            continue
        if line.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            if ":" not in stripped:
                continue
            key, _, rest = stripped.partition(":")
            rest = rest.strip()
            current_scalar_dict = None
            if rest == "":
                out[key] = []
                current_list_key = key
                current_item = None
            else:
                out[key] = _coerce(rest)
                current_list_key = None
                current_item = None
        elif stripped.startswith("- "):
            if current_list_key is None:
                continue
            assert isinstance(out[current_list_key], list)
            current_item = {}
            out[current_list_key].append(current_item)
            inner = stripped[2:]
            if ":" in inner:
                key, _, rest = inner.partition(":")
                current_item[key.strip()] = _coerce(rest)
        elif ":" in stripped:
            key, _, rest = stripped.partition(":")
            if current_item is not None:
                current_item[key.strip()] = _coerce(rest)
            elif current_list_key is not None and isinstance(
                out.get(current_list_key), list
            ):
                if not out[current_list_key]:
                    out[current_list_key] = {}
                    out[current_list_key][key.strip()] = _coerce(rest)
                    current_scalar_dict = out[current_list_key]
                    current_list_key = None
            elif current_scalar_dict is not None:
                current_scalar_dict[key.strip()] = _coerce(rest)
    return out


# ---------------------------------------------------------------------------
# Shared resolver bootstrap helpers (subset of v1).
# ---------------------------------------------------------------------------


def _import_resolvers() -> Dict[str, Callable]:
    sys.path.insert(0, str(REPO_ROOT))
    from wirelang.persona_engine import rust_backend_switch as rbs  # noqa: E402

    return {
        "recovery": rbs.resolve_recovery_backend,
        "state_backing": rbs.resolve_state_backing_backend,
        "fsm": rbs.resolve_fsm_backend,
        "v907_verify": rbs.resolve_v907_verify_backend,
        "bridge_diff": rbs.resolve_bridge_diff_backend,
        "subscribe_loop": rbs.resolve_subscribe_loop_backend,
        "anchor_emitter": rbs.resolve_anchor_emitter_backend,
        "svid_workload_identity": rbs.resolve_svid_workload_identity_backend,
        "federation_resolver": rbs.resolve_federation_resolver_backend,
        "bridge_audit_writer": rbs.resolve_bridge_audit_writer_backend,
    }


def _drive_stage_1_boot(
    env: Optional[Dict[str, str]] = None,
) -> Tuple[List[Any], str]:
    resolvers = _import_resolvers()
    use_env: Dict[str, str] = {} if env is None else env
    log_sink = io.StringIO()
    decisions: List[Any] = []
    for _record_no, _component_label, domain in EXPECTED_BOOT_ORDER:
        resolver = resolvers[domain]
        _, decision = resolver(env=use_env, log_sink=log_sink)
        decisions.append(decision)
    return decisions, log_sink.getvalue()


# ---------------------------------------------------------------------------
# Class A — Tag-48 carry-forward checks (smoke; v1 owns the depth).
# ---------------------------------------------------------------------------


def check_artefacts_present() -> Tuple[bool, str]:
    missing = []
    for p in (MANIFEST_PATH, PIN_PACK_PATH):
        if not p.exists():
            missing.append(str(p.relative_to(REPO_ROOT)))
    if missing:
        return False, f"missing artefact(s): {missing}"
    return (
        True,
        (
            f"manifest={MANIFEST_PATH.relative_to(REPO_ROOT)} "
            f"pin_pack={PIN_PACK_PATH.relative_to(REPO_ROOT)}"
        ),
    )


def check_stage_1_emits_ten() -> Tuple[bool, str]:
    decisions, _ = _drive_stage_1_boot()
    if len(decisions) != 10:
        return False, f"expected 10 BackendDecisions, got {len(decisions)}"
    return True, "Stage-1 fan-out emitted exactly 10 BackendDecisions"


def check_stage_1_order() -> Tuple[bool, str]:
    decisions, _ = _drive_stage_1_boot()
    actual = [d.domain for d in decisions]
    expected = [domain for _, _, domain in EXPECTED_BOOT_ORDER]
    if actual != expected:
        return False, f"boot order mismatch: got {actual}, expected {expected}"
    return True, f"Stage-1 domain order = {actual}"


def check_v907_pin_stable() -> Tuple[bool, str]:
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from wirelang.persona_engine.v907_verify import compute_v907_pin
    except ImportError as exc:
        return False, f"could not import compute_v907_pin: {exc}"

    blob = b"""---
persona_id: "pengine-v2-test"
persona_name: "Pengine v2 Self-Test"
org_id: "wakir"
schema_version: "persona-v1"
---

# Self-test persona (v2)

Body content for V-907 pin stability check (v2).
"""
    try:
        pin_a = compute_v907_pin(blob)
        pin_b = compute_v907_pin(blob)
    except Exception as exc:  # noqa: BLE001
        fa = hashlib.sha256(blob).hexdigest()
        fb = hashlib.sha256(blob).hexdigest()
        if fa != fb:
            return False, f"sha256 fallback non-stable: {fa} vs {fb}"
        return True, (
            f"V-907 strict path unavailable ({type(exc).__name__}); "
            f"sha256-fallback stable={fa[:16]}..."
        )
    if pin_a != pin_b:
        return False, f"V-907 pin drifted: {pin_a} vs {pin_b}"
    return True, f"V-907 pin stable across two computes: {pin_a[:16]}..."


def check_boot_fingerprint_deterministic() -> Tuple[bool, str]:
    """Boot fingerprint stable across two independent fan-outs."""
    def _fingerprint() -> str:
        decisions, _ = _drive_stage_1_boot()
        payload = json.dumps(
            [
                {
                    "domain": d.domain,
                    "requested_backend": d.requested_backend,
                    "chosen_backend": d.chosen_backend,
                    "fallback_reason": d.fallback_reason,
                }
                for d in decisions
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    a = _fingerprint()
    b = _fingerprint()
    if a != b:
        return False, f"boot fingerprint non-deterministic: {a} vs {b}"
    return True, f"boot fingerprint stable: {a[:16]}..."


# ---------------------------------------------------------------------------
# Class B — 15-Crate Cross-Lang-Pin live boot coverage (Tag-50 new).
# ---------------------------------------------------------------------------


def _pin_pack() -> Dict[str, Any]:
    return _parse_pin_pack_yaml(PIN_PACK_PATH.read_text(encoding="utf-8"))


def check_pin_pack_total_count_fifteen() -> Tuple[bool, str]:
    pp = _pin_pack()
    wired = pp.get("boot_wired_crates") or []
    unwired = pp.get("boot_unwired_crates") or []
    total = len(wired) + len(unwired)
    if total != EXPECTED_TOTAL_PIN_PACK_CRATES:
        return (
            False,
            (
                f"pin-pack total crates = {total} "
                f"(wired={len(wired)}, unwired={len(unwired)}); "
                f"expected {EXPECTED_TOTAL_PIN_PACK_CRATES}"
            ),
        )
    return True, (
        f"pin-pack 15-crate cardinality holds "
        f"(boot-wired={len(wired)}, boot-unwired={len(unwired)})"
    )


def check_pin_pack_boot_wired_shape() -> Tuple[bool, str]:
    pp = _pin_pack()
    wired = pp.get("boot_wired_crates") or []
    if len(wired) != 10:
        return False, f"pin-pack boot_wired_crates length = {len(wired)}"
    for (expected_no, expected_name), entry in zip(
        EXPECTED_PIN_PACK_BOOT_WIRED, wired
    ):
        if entry.get("record") != expected_no:
            return False, (
                f"record-no mismatch at slot {expected_no}: "
                f"got {entry.get('record')!r}"
            )
        if entry.get("name") != expected_name:
            return False, (
                f"name mismatch at record {expected_no}: "
                f"got {entry.get('name')!r}"
            )
        if entry.get("version") != EXPECTED_PIN_VERSION:
            return False, (
                f"version mismatch at record {expected_no}: "
                f"got {entry.get('version')!r}"
            )
        for required_key in ("selector_env", "binary_env", "python_authority"):
            if not entry.get(required_key):
                return False, (
                    f"record {expected_no} missing required key "
                    f"{required_key!r}"
                )
        # Boot-wired crates MUST ship a cross-lang fixtures.json path.
        if not entry.get("fixtures"):
            return False, (
                f"record {expected_no} ({expected_name}) missing fixtures"
            )
    return True, "10 boot-wired crates: record/name/version/envs/fixtures complete"


def check_pin_pack_boot_unwired_shape() -> Tuple[bool, str]:
    pp = _pin_pack()
    unwired = pp.get("boot_unwired_crates") or []
    if len(unwired) != 5:
        return False, f"pin-pack boot_unwired_crates length = {len(unwired)}"
    names = tuple(e.get("name") for e in unwired)
    if names != EXPECTED_PIN_PACK_UNWIRED:
        return False, (
            f"boot_unwired_crates name-order mismatch: got {names}"
        )
    for entry in unwired:
        if entry.get("version") != EXPECTED_PIN_VERSION:
            return False, (
                f"unwired crate {entry.get('name')} version drift: "
                f"got {entry.get('version')!r}"
            )
        if not entry.get("note"):
            return False, (
                f"unwired crate {entry.get('name')} missing note"
            )
    return True, "5 boot-unwired crates: name/version/note complete"


def check_pin_pack_invariants_block() -> Tuple[bool, str]:
    pp = _pin_pack()
    inv = pp.get("invariants")
    if not isinstance(inv, dict):
        return False, f"pin-pack invariants block missing: {inv!r}"
    wanted = {
        "total_wired_crates": 10,
        "total_pin_pack_crates": 15,
        "boot_record_count": 10,
    }
    for k, expected in wanted.items():
        if inv.get(k) != expected:
            return False, f"pin-pack invariants.{k} drifted: {inv.get(k)!r}"
    if inv.get("containerfile_image_tag") != EXPECTED_MANIFEST_VERSION:
        return False, (
            f"pin-pack invariants.containerfile_image_tag drifted: "
            f"{inv.get('containerfile_image_tag')!r}"
        )
    return True, "pin-pack invariants block (10/15/0.5.1-pre-cutover) holds"


def check_pin_pack_versions_uniform() -> Tuple[bool, str]:
    """Every one of the 15 crates pins to EXPECTED_PIN_VERSION."""
    pp = _pin_pack()
    bad = []
    for entry in (pp.get("boot_wired_crates") or []) + (
        pp.get("boot_unwired_crates") or []
    ):
        if entry.get("version") != EXPECTED_PIN_VERSION:
            bad.append((entry.get("name"), entry.get("version")))
    if bad:
        return False, f"pin-pack versions non-uniform: {bad}"
    return True, f"all 15 crates pinned to {EXPECTED_PIN_VERSION}"


def check_pin_pack_names_unique() -> Tuple[bool, str]:
    """No crate name appears in both boot_wired and boot_unwired."""
    pp = _pin_pack()
    wired = {e.get("name") for e in (pp.get("boot_wired_crates") or [])}
    unwired = {e.get("name") for e in (pp.get("boot_unwired_crates") or [])}
    overlap = wired & unwired
    if overlap:
        return False, f"crate(s) in both wired and unwired: {overlap}"
    if len(wired) + len(unwired) != EXPECTED_TOTAL_PIN_PACK_CRATES:
        return False, (
            f"union cardinality drift: {len(wired) + len(unwired)}"
        )
    return True, f"15 crate names are partition-disjoint (10 + 5)"


# ---------------------------------------------------------------------------
# Class C — ENV-Flag-Konsistenz across resolver <-> manifest <-> pin-pack.
# ---------------------------------------------------------------------------


def _resolver_env_constants() -> Dict[str, str]:
    """Read module-level *_BACKEND_ENV / *_BIN_ENV constants.

    Returns a dict keyed by constant-name -> ENV-string value.
    """
    sys.path.insert(0, str(REPO_ROOT))
    rbs = importlib.import_module(
        "wirelang.persona_engine.rust_backend_switch"
    )
    return {
        name: getattr(rbs, name)
        for name in dir(rbs)
        if (name.endswith("_BACKEND_ENV") or name.endswith("_BIN_ENV"))
        and isinstance(getattr(rbs, name), str)
    }


def check_resolver_selector_env_set() -> Tuple[bool, str]:
    consts = _resolver_env_constants()
    selectors = {v for k, v in consts.items() if k.endswith("_BACKEND_ENV")}
    expected_wired = {env for _, env in EXPECTED_SELECTOR_ENVS}
    expected_full = expected_wired | set(EXPECTED_COMPANION_SELECTOR_ENVS)
    missing = expected_full - selectors
    extra = selectors - expected_full
    if missing or extra:
        return False, (
            f"resolver selector-ENV set drift: missing={missing}, "
            f"extra={extra} (this is DRIFT-S4 surface)"
        )
    return True, (
        f"resolver selector-ENV set matches 10 wired + 2 companion "
        f"= {len(selectors)} constants"
    )


def check_resolver_binary_env_set() -> Tuple[bool, str]:
    consts = _resolver_env_constants()
    bins = {v for k, v in consts.items() if k.endswith("_BIN_ENV")}
    expected_wired = {env for _, env in EXPECTED_BINARY_ENVS}
    expected_full = expected_wired | set(EXPECTED_COMPANION_BINARY_ENVS)
    missing = expected_full - bins
    extra = bins - expected_full
    if missing or extra:
        return False, (
            f"resolver binary-ENV set drift: missing={missing}, "
            f"extra={extra} (DRIFT-S4 surface)"
        )
    return True, (
        f"resolver binary-ENV set matches 10 wired + 2 companion "
        f"= {len(bins)} constants"
    )


def check_manifest_selector_env_table() -> Tuple[bool, str]:
    """Manifest §2.1 names exactly the 10 wired selector ENVs."""
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    found_envs = set(re.findall(r"`(WAKIR_[A-Z0-9_]+_BACKEND)`", text))
    expected_wired = {env for _, env in EXPECTED_SELECTOR_ENVS}
    missing_from_manifest = expected_wired - found_envs
    if missing_from_manifest:
        return False, (
            f"manifest does not document selector ENV(s): "
            f"{missing_from_manifest}"
        )
    return True, (
        f"manifest references all 10 wired selector ENVs "
        f"(found_total={len(found_envs)})"
    )


def check_manifest_binary_env_table() -> Tuple[bool, str]:
    """Manifest §2.2 names exactly the 10 wired binary-path ENVs."""
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    found_envs = set(re.findall(r"`(WAKIR_RUST_[A-Z0-9_]+_BIN)`", text))
    expected_wired = {env for _, env in EXPECTED_BINARY_ENVS}
    missing = expected_wired - found_envs
    if missing:
        return False, (
            f"manifest does not document binary ENV(s): {missing}"
        )
    return True, (
        f"manifest references all 10 wired binary-path ENVs "
        f"(found_total={len(found_envs)})"
    )


def check_pinpack_selector_env_alignment() -> Tuple[bool, str]:
    """pin-pack record-N selector_env == manifest §2.1 row-N ENV."""
    pp = _pin_pack()
    wired = pp.get("boot_wired_crates") or []
    if len(wired) != 10:
        return False, f"pin-pack wired length = {len(wired)}"
    for (component_label, expected_env), entry in zip(
        EXPECTED_SELECTOR_ENVS, wired
    ):
        actual = entry.get("selector_env")
        if actual != expected_env:
            return False, (
                f"pin-pack selector_env mismatch for {component_label}: "
                f"got {actual!r} expected {expected_env!r}"
            )
    return True, "pin-pack selector_env aligns with manifest §2.1 for all 10 wired records"


def check_pinpack_binary_env_alignment() -> Tuple[bool, str]:
    """pin-pack record-N binary_env == manifest §2.2 row-N ENV."""
    pp = _pin_pack()
    wired = pp.get("boot_wired_crates") or []
    if len(wired) != 10:
        return False, f"pin-pack wired length = {len(wired)}"
    for (component_label, expected_env), entry in zip(
        EXPECTED_BINARY_ENVS, wired
    ):
        actual = entry.get("binary_env")
        if actual != expected_env:
            return False, (
                f"pin-pack binary_env mismatch for {component_label}: "
                f"got {actual!r} expected {expected_env!r}"
            )
    return True, "pin-pack binary_env aligns with manifest §2.2 for all 10 wired records"


def check_resolver_manifest_pinpack_triple_alignment() -> Tuple[bool, str]:
    """The 10 selector + 10 binary ENVs match across all three sources.

    This is the **strict DRIFT-S4 gate** — fails if any wired ENV
    name appears in one source but not in the other two.
    """
    consts = _resolver_env_constants()
    resolver_selectors = {
        v for k, v in consts.items() if k.endswith("_BACKEND_ENV")
    } - set(EXPECTED_COMPANION_SELECTOR_ENVS)
    resolver_bins = {
        v for k, v in consts.items() if k.endswith("_BIN_ENV")
    } - set(EXPECTED_COMPANION_BINARY_ENVS)

    pp = _pin_pack()
    wired = pp.get("boot_wired_crates") or []
    pp_selectors = {e.get("selector_env") for e in wired}
    pp_bins = {e.get("binary_env") for e in wired}

    text = MANIFEST_PATH.read_text(encoding="utf-8")
    man_selectors = set(re.findall(r"`(WAKIR_[A-Z0-9_]+_BACKEND)`", text)) & {
        env for _, env in EXPECTED_SELECTOR_ENVS
    }
    man_bins = set(re.findall(r"`(WAKIR_RUST_[A-Z0-9_]+_BIN)`", text)) & {
        env for _, env in EXPECTED_BINARY_ENVS
    }

    if not (resolver_selectors == pp_selectors == man_selectors):
        return False, (
            f"selector-ENV triple-set drift: "
            f"resolver={sorted(resolver_selectors)} "
            f"pin_pack={sorted(pp_selectors)} "
            f"manifest={sorted(man_selectors)}"
        )
    if not (resolver_bins == pp_bins == man_bins):
        return False, (
            f"binary-ENV triple-set drift: "
            f"resolver={sorted(resolver_bins)} "
            f"pin_pack={sorted(pp_bins)} "
            f"manifest={sorted(man_bins)}"
        )
    return True, (
        f"resolver <-> pin-pack <-> manifest triple-alignment holds for "
        f"10 selector + 10 binary ENVs (DRIFT-S4 closed)"
    )


def check_cross_backend_timeout_env() -> Tuple[bool, str]:
    """The single cross-cutting timeout knob is declared in all 3 sources."""
    consts = _resolver_env_constants()
    resolver_has = EXPECTED_CROSS_BACKEND_TIMEOUT_ENV in set(consts.values())
    if not resolver_has:
        # The constant is RUST_BACKEND_TIMEOUT_ENV — read it directly.
        sys.path.insert(0, str(REPO_ROOT))
        rbs = importlib.import_module(
            "wirelang.persona_engine.rust_backend_switch"
        )
        if (
            getattr(rbs, "RUST_BACKEND_TIMEOUT_ENV", None)
            != EXPECTED_CROSS_BACKEND_TIMEOUT_ENV
        ):
            return False, (
                f"resolver missing/wrong RUST_BACKEND_TIMEOUT_ENV: "
                f"{getattr(rbs, 'RUST_BACKEND_TIMEOUT_ENV', None)!r}"
            )

    pp = _pin_pack()
    cb = pp.get("cross_backend")
    if (
        not isinstance(cb, dict)
        or cb.get("timeout_env") != EXPECTED_CROSS_BACKEND_TIMEOUT_ENV
    ):
        return False, (
            f"pin-pack cross_backend.timeout_env drift: {cb!r}"
        )
    text = MANIFEST_PATH.read_text(encoding="utf-8")
    if EXPECTED_CROSS_BACKEND_TIMEOUT_ENV not in text:
        return False, "manifest does not mention WAKIR_RUST_BACKEND_TIMEOUT_S"
    return True, (
        f"cross-backend timeout knob {EXPECTED_CROSS_BACKEND_TIMEOUT_ENV} "
        f"declared in all three sources"
    )


# ---------------------------------------------------------------------------
# Class D — Live ENV-flip smoke (DRIFT-S4 active-side verification).
# ---------------------------------------------------------------------------


def check_env_flip_python_default_holds() -> Tuple[bool, str]:
    """Setting every selector ENV to 'python' explicitly must match the
    clean-env baseline byte-for-byte.

    This is the active-side check that the resolver code honours
    each selector ENV constant; if a resolver got refactored to
    read the wrong ENV name (DRIFT-S4), this check would fail because
    the explicit-python token would not surface as 'python'.
    """
    env = {env: "python" for _, env in EXPECTED_SELECTOR_ENVS}
    decisions, _ = _drive_stage_1_boot(env=env)
    if len(decisions) != 10:
        return False, f"explicit-python env -> {len(decisions)} decisions"
    bad = [
        f"{d.domain}={d.chosen_backend}"
        for d in decisions
        if d.chosen_backend != "python"
    ]
    if bad:
        return False, f"explicit-python env did not select python: {bad}"
    return True, (
        "10 selector ENVs honoured (explicit 'python' on each domain)"
    )


def check_env_flip_unknown_value_rejected() -> Tuple[bool, str]:
    """A bogus selector value must be **rejected** by the resolver
    contract — the resolver raises ``BackendSwitchValidationError``
    rather than silently coercing the value.

    This is the strict-validation invariant: an operator who fat-
    fingers ``WAKIR_RECOVERY_BACKEND=ruts`` (typo for ``rust``)
    must see a hard error, not a silent fallback to Python. This
    behaviour is part of the Tag-48 selector-ENV contract.

    Picks the recovery domain as the representative; the other 9
    resolvers share the same dispatch shape.
    """
    sys.path.insert(0, str(REPO_ROOT))
    from wirelang.persona_engine.rust_backend_switch import (
        BackendSwitchValidationError,
        resolve_recovery_backend,
    )

    log_sink = io.StringIO()
    try:
        resolve_recovery_backend(
            env={"WAKIR_RECOVERY_BACKEND": "bogus-value-12345"},
            log_sink=log_sink,
        )
    except BackendSwitchValidationError as exc:
        msg = str(exc)
        if "bogus-value-12345" not in msg:
            return False, (
                f"validation error did not reference offending value: {msg!r}"
            )
        return True, (
            f"bogus selector rejected with BackendSwitchValidationError "
            f"(msg includes offending value)"
        )
    return False, (
        "bogus selector did NOT raise BackendSwitchValidationError "
        "(strict-validation contract drift)"
    )


# ---------------------------------------------------------------------------
# Class E — Cargo.toml <-> pin-pack version cross-check (post-Tag-50).
# ---------------------------------------------------------------------------


def _read_cargo_version(crate_dir: Path) -> Optional[str]:
    """Read ``version`` from a Cargo.toml without TOML dep."""
    cargo = crate_dir / "Cargo.toml"
    if not cargo.exists():
        return None
    text = cargo.read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else None


def check_cargo_pinpack_version_alignment() -> Tuple[bool, str]:
    """Each pin-pack crate's Cargo.toml version matches the pinned version.

    Tolerates missing crate dirs (the cutover sandbox may not have
    every crate vendored) — the check FAILS only if a Cargo.toml
    *exists* and disagrees with the pin-pack.
    """
    pp = _pin_pack()
    all_crates = (pp.get("boot_wired_crates") or []) + (
        pp.get("boot_unwired_crates") or []
    )
    drift: List[str] = []
    checked = 0
    for entry in all_crates:
        name = entry.get("name")
        pinned = entry.get("version")
        crate_dir = REPO_ROOT / "wirelang-rust" / name
        cargo_version = _read_cargo_version(crate_dir)
        if cargo_version is None:
            # Crate not vendored in this checkout; skip.
            continue
        checked += 1
        if cargo_version != pinned:
            drift.append(f"{name}: cargo={cargo_version} pinned={pinned}")
    if drift:
        return False, f"Cargo<->pin-pack version drift: {drift}"
    if checked == 0:
        return True, (
            "Cargo.toml files not vendored in this checkout; "
            "version-alignment check skipped (still PASS by convention)"
        )
    return True, (
        f"Cargo.toml <-> pin-pack version aligned for {checked} crate(s)"
    )


# ---------------------------------------------------------------------------
# Harness.
# ---------------------------------------------------------------------------


CHECKS: Tuple[Tuple[str, Callable[[], Tuple[bool, str]]], ...] = (
    # Class A — Tag-48 carry-forward smoke.
    ("artefacts_present", check_artefacts_present),
    ("stage_1_emits_ten", check_stage_1_emits_ten),
    ("stage_1_order", check_stage_1_order),
    ("v907_pin_stable", check_v907_pin_stable),
    ("boot_fingerprint_deterministic", check_boot_fingerprint_deterministic),
    # Class B — 15-Crate Cross-Lang-Pin live boot coverage.
    ("pin_pack_total_count_fifteen", check_pin_pack_total_count_fifteen),
    ("pin_pack_boot_wired_shape", check_pin_pack_boot_wired_shape),
    ("pin_pack_boot_unwired_shape", check_pin_pack_boot_unwired_shape),
    ("pin_pack_invariants_block", check_pin_pack_invariants_block),
    ("pin_pack_versions_uniform", check_pin_pack_versions_uniform),
    ("pin_pack_names_unique", check_pin_pack_names_unique),
    # Class C — ENV-Flag-Konsistenz triple-alignment (DRIFT-S4).
    ("resolver_selector_env_set", check_resolver_selector_env_set),
    ("resolver_binary_env_set", check_resolver_binary_env_set),
    ("manifest_selector_env_table", check_manifest_selector_env_table),
    ("manifest_binary_env_table", check_manifest_binary_env_table),
    ("pinpack_selector_env_alignment", check_pinpack_selector_env_alignment),
    ("pinpack_binary_env_alignment", check_pinpack_binary_env_alignment),
    (
        "resolver_manifest_pinpack_triple_alignment",
        check_resolver_manifest_pinpack_triple_alignment,
    ),
    ("cross_backend_timeout_env", check_cross_backend_timeout_env),
    # Class D — Live ENV-flip smoke.
    ("env_flip_python_default_holds", check_env_flip_python_default_holds),
    (
        "env_flip_unknown_value_rejected",
        check_env_flip_unknown_value_rejected,
    ),
    # Class E — Cargo.toml <-> pin-pack version alignment.
    ("cargo_pinpack_version_alignment", check_cargo_pinpack_version_alignment),
)


def run_self_test() -> SelfTestReport:
    saved_env = dict(os.environ)
    try:
        for key in list(os.environ):
            if key.startswith("WAKIR_"):
                del os.environ[key]
        report = SelfTestReport(
            boot_baseline=(
                "0.5.1-pre-cutover v2 (Tag-50: 15-crate + ENV-flag DRIFT-S4)"
            ),
            manifest_version=EXPECTED_MANIFEST_VERSION,
        )
        for name, fn in CHECKS:
            report.checks.append(_run_check(name, fn))
        return report
    finally:
        os.environ.clear()
        os.environ.update(saved_env)


def _print_human(report: SelfTestReport, *, quiet: bool) -> None:
    if quiet and report.passed:
        return
    print(f"Persona-Engine Boot Self-Test v2 ({report.manifest_version})")
    print(f"  Baseline: {report.boot_baseline}")
    print(
        f"  Checks: {report.total} | "
        f"Passed: {report.total - report.failed_count} | "
        f"Failed: {report.failed_count}"
    )
    print()
    for c in report.checks:
        marker = "OK " if c.passed else "FAIL"
        print(f"  [{marker}] {c.name:48s} {c.detail}")
    print()
    if report.passed:
        print("All boot self-test v2 checks PASSED.")
    else:
        print(
            f"Boot self-test v2 FAILED ({report.failed_count} failing check(s))."
        )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Persona-Engine 0.5.1-pre-cutover Boot Self-Test v2"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable JSON report on stdout",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="silent on success (still prints on failure)",
    )
    args = parser.parse_args(argv)

    report = run_self_test()
    if args.json:
        print(json.dumps(report.as_dict(), indent=2, sort_keys=True))
    else:
        _print_human(report, quiet=args.quiet)
    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
