# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-48 hermetic suite for the bridge-audit-writer 10th-record wire-in.

These tests pin the byte-shape of the Tag-48 wire-in. The Tag-45
0.5.0-pre-cutover manifest defined the ``BridgeAuditWriterBackend``
enum and the ``resolve_bridge_audit_writer_backend`` resolver as a
scaffold but **held them back from the Stage-1 boot fan-out** so the
Phase-3a Doppelbetrieb boot-fingerprint hash would stay stable
across the 0.4.2-pilot -> 0.5.0-pre-cutover engine swap. Tag-48
promotes the scaffold into a live resolver call and extends the
manifest to ten boot-wired components.

Test inventory
--------------

The 25 tests below cover four planes:

* Resolver-API surface: function imports, enum closure, env-var
  validation rejecting unknown values, default-python posture.
* Engine boot wire-in: engine.py imports the resolver, the boot
  fan-out emits a 10th decision with the bridge_audit_writer domain,
  the 10th decision sits at the tail of the fan-out (not in the
  middle).
* Manifest/pin-pack consistency: the new 0.5.1-pre-cutover manifest
  declares the 10th record, the Tag-45 0.5.0 historical anchor
  remains in-tree at byte-stable shape, the bridge-audit-writer
  crate is now in pin-pack ``boot_wired_crates`` (vs. previously
  ``boot_unwired_crates``).
* Backward-compat: Default boot fingerprint is deterministic; the
  10th record extends the 9-record fingerprint via one extra
  4-tuple at the tail (no reorder of records 1..9).

Hermetic envelope: no network, no subprocess, no Rust binary. Pure
file-inspection + in-process resolver fan-out.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import re
from pathlib import Path
from typing import Any, Dict

import pytest

yaml = pytest.importorskip(
    "yaml",
    reason="PyYAML not available in this lane; pin-pack tests skipped.",
)


REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.1-pre-cutover.md"
)
LEGACY_MANIFEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "persona_engine"
    / "MANIFEST-0.5.0-pre-cutover.md"
)
PIN_PACK_PATH = (
    REPO_ROOT
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.1-pre-cutover.yaml"
)
LEGACY_PIN_PACK_PATH = (
    REPO_ROOT
    / "infra"
    / "persona-engine"
    / "pin-pack-0.5.0-pre-cutover.yaml"
)
ENGINE_PATH = REPO_ROOT / "wirelang" / "persona_engine" / "engine.py"
RUST_BACKEND_SWITCH_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "rust_backend_switch.py"
)
CRATES_ROOT = REPO_ROOT / "wirelang-rust" / "crates"


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def manifest_text() -> str:
    return MANIFEST_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pin_pack() -> dict:
    return yaml.safe_load(PIN_PACK_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def engine_src() -> str:
    return ENGINE_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rbs_src() -> str:
    return RUST_BACKEND_SWITCH_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="function")
def clean_wakir_env(monkeypatch):
    """Strip every WAKIR_* env var so resolvers pick defaults."""
    for key in list(os.environ):
        if key.startswith("WAKIR_"):
            monkeypatch.delenv(key, raising=False)
    yield


def _drive_stage_1(env: Dict[str, str] | None = None):
    """Replay the engine.py Stage-1 fan-out in clean-env baseline."""
    from wirelang.persona_engine import rust_backend_switch as rbs

    use_env: Dict[str, str] = {} if env is None else env
    log_sink = io.StringIO()
    order = [
        rbs.resolve_recovery_backend,
        rbs.resolve_state_backing_backend,
        rbs.resolve_fsm_backend,
        rbs.resolve_v907_verify_backend,
        rbs.resolve_bridge_diff_backend,
        rbs.resolve_subscribe_loop_backend,
        rbs.resolve_anchor_emitter_backend,
        rbs.resolve_svid_workload_identity_backend,
        rbs.resolve_federation_resolver_backend,
        rbs.resolve_bridge_audit_writer_backend,
    ]
    decisions = []
    for resolver in order:
        _, dec = resolver(env=use_env, log_sink=log_sink)
        decisions.append(dec)
    return decisions, log_sink.getvalue()


# ---------------------------------------------------------------------------
# 1. Resolver-API surface.
# ---------------------------------------------------------------------------


def test_01_resolver_function_importable() -> None:
    """``resolve_bridge_audit_writer_backend`` is importable from
    the public rust_backend_switch surface."""
    from wirelang.persona_engine.rust_backend_switch import (
        resolve_bridge_audit_writer_backend,
    )

    assert callable(resolve_bridge_audit_writer_backend)


def test_02_enum_has_two_values() -> None:
    """``BridgeAuditWriterBackend`` is a closed two-value enum."""
    from wirelang.persona_engine.rust_backend_switch import (
        BridgeAuditWriterBackend,
        VALID_BRIDGE_AUDIT_WRITER_BACKEND_VALUES,
    )

    assert {b.value for b in BridgeAuditWriterBackend} == {"python", "rust"}
    assert VALID_BRIDGE_AUDIT_WRITER_BACKEND_VALUES == ("python", "rust")


def test_03_env_var_constants_exposed() -> None:
    """Selector ENV + binary-path ENV + default binary path are public."""
    from wirelang.persona_engine.rust_backend_switch import (
        BRIDGE_AUDIT_WRITER_BACKEND_ENV,
        DEFAULT_RUST_BRIDGE_AUDIT_WRITER_BIN,
        RUST_BRIDGE_AUDIT_WRITER_BIN_ENV,
    )

    assert BRIDGE_AUDIT_WRITER_BACKEND_ENV == "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"
    assert RUST_BRIDGE_AUDIT_WRITER_BIN_ENV == (
        "WAKIR_RUST_BRIDGE_AUDIT_WRITER_BIN"
    )
    assert DEFAULT_RUST_BRIDGE_AUDIT_WRITER_BIN == (
        "/opt/wakir/bin/wakir-persona-engine-bridge-audit-writer"
    )


def test_04_clean_env_defaults_to_rust_with_graceful_python_fallback(clean_wakir_env) -> None:
    """Tag-80 Welle-3 Cutover: clean env yields ``requested='rust'``
    and graceful fallback to ``chosen='python'`` on Sandbox-CI
    without rust binary, with ``fallback_reason='binary_missing'``."""
    from wirelang.persona_engine.rust_backend_switch import (
        DEFAULT_RUST_BRIDGE_AUDIT_WRITER_BIN,
        resolve_bridge_audit_writer_backend,
    )

    _, decision = resolve_bridge_audit_writer_backend(env={})
    assert decision.domain == "bridge_audit_writer"
    assert decision.chosen_backend == "python"  # graceful fallback
    assert decision.requested_backend == "rust"
    assert decision.fallback_reason == "binary_missing"
    assert decision.bin_path == DEFAULT_RUST_BRIDGE_AUDIT_WRITER_BIN


def test_05_explicit_python_marks_explicit_fallback(clean_wakir_env) -> None:
    """``WAKIR_BRIDGE_AUDIT_WRITER_BACKEND=python`` carries the
    ``explicit_python`` fallback_reason token (mirror of the eight
    sibling resolvers)."""
    from wirelang.persona_engine.rust_backend_switch import (
        resolve_bridge_audit_writer_backend,
    )

    _, decision = resolve_bridge_audit_writer_backend(
        env={"WAKIR_BRIDGE_AUDIT_WRITER_BACKEND": "python"}
    )
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "explicit_python"


def test_06_unknown_env_value_raises_validation_error(clean_wakir_env) -> None:
    """Unknown selector values raise ``BackendSwitchValidationError``."""
    from wirelang.persona_engine.rust_backend_switch import (
        BackendSwitchValidationError,
        resolve_bridge_audit_writer_backend,
    )

    with pytest.raises(BackendSwitchValidationError) as excinfo:
        resolve_bridge_audit_writer_backend(
            env={"WAKIR_BRIDGE_AUDIT_WRITER_BACKEND": "rust_natskv"}
        )
    assert excinfo.value.env_var == "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"
    assert excinfo.value.value == "rust_natskv"


def test_07_rust_requested_with_missing_bin_falls_back_to_python(
    clean_wakir_env,
) -> None:
    """``rust`` selector + absent binary -> graceful Python fallback."""
    from wirelang.persona_engine.rust_backend_switch import (
        resolve_bridge_audit_writer_backend,
    )

    def fake_probe(_path: str) -> tuple[bool, str | None]:
        return False, "binary_missing"

    backend, decision = resolve_bridge_audit_writer_backend(
        env={
            "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND": "rust",
            "WAKIR_RUST_BRIDGE_AUDIT_WRITER_BIN": (
                "/nonexistent/bridge-audit-writer-bin"
            ),
        },
        binary_probe=fake_probe,
    )
    assert backend.value == "python"
    assert decision.requested_backend == "rust"
    assert decision.chosen_backend == "python"
    assert decision.fallback_reason == "binary_missing"


def test_08_rust_requested_with_present_bin_picks_rust(clean_wakir_env) -> None:
    """``rust`` selector + present binary -> RUST backend."""
    from wirelang.persona_engine.rust_backend_switch import (
        BridgeAuditWriterBackend,
        resolve_bridge_audit_writer_backend,
    )

    def fake_probe(_path: str) -> tuple[bool, str | None]:
        return True, None

    backend, decision = resolve_bridge_audit_writer_backend(
        env={
            "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND": "rust",
            "WAKIR_RUST_BRIDGE_AUDIT_WRITER_BIN": "/usr/local/bin/fake",
        },
        binary_probe=fake_probe,
    )
    assert backend is BridgeAuditWriterBackend.RUST
    assert decision.chosen_backend == "rust"
    assert decision.fallback_reason is None
    assert decision.bin_path == "/usr/local/bin/fake"


def test_09_auftrag_alias_dispatches_to_resolver() -> None:
    """Underscore-prefixed auftrag alias dispatches to the public resolver."""
    from wirelang.persona_engine import rust_backend_switch as rbs

    alias = getattr(rbs, "_select_bridge_audit_writer_backend")
    assert alias is rbs.resolve_bridge_audit_writer_backend


# ---------------------------------------------------------------------------
# 2. Engine boot wire-in.
# ---------------------------------------------------------------------------


def test_10_engine_imports_resolver(engine_src: str) -> None:
    """engine.py imports ``resolve_bridge_audit_writer_backend``."""
    assert "resolve_bridge_audit_writer_backend" in engine_src, (
        "Tag-48 wire-in requires engine.py to import the resolver from "
        "rust_backend_switch."
    )


def test_11_engine_invokes_resolver_in_boot(engine_src: str) -> None:
    """engine.py calls the resolver inside the boot() method."""
    # The call lives between the federation_resolver block and the
    # `Open the persona_engine.boot span` comment marker.
    pattern = re.compile(
        r"resolve_bridge_audit_writer_backend\s*\(",
    )
    assert pattern.search(engine_src), (
        "engine.py must invoke resolve_bridge_audit_writer_backend() in "
        "the boot fan-out (not just import it)."
    )


def test_12_engine_records_decision_on_self(engine_src: str) -> None:
    """engine.py stashes the resolver output on ``self._bridge_audit_writer_*``."""
    assert "self._bridge_audit_writer_backend" in engine_src
    assert "self._bridge_audit_writer_backend_decision" in engine_src


def test_13_stage_1_emits_ten_decisions(clean_wakir_env) -> None:
    """Replaying the engine.py Stage-1 fan-out emits 10 records."""
    decisions, _ = _drive_stage_1()
    assert len(decisions) == 10


def test_14_stage_1_tenth_decision_domain_is_bridge_audit_writer(
    clean_wakir_env,
) -> None:
    """The 10th record carries domain='bridge_audit_writer'."""
    decisions, _ = _drive_stage_1()
    assert decisions[-1].domain == "bridge_audit_writer"


def test_15_stage_1_first_nine_decisions_match_tag45_order(
    clean_wakir_env,
) -> None:
    """Records 1..9 retain the Tag-45 boot order byte-for-byte."""
    decisions, _ = _drive_stage_1()
    first_nine = [d.domain for d in decisions[:9]]
    assert first_nine == [
        "recovery",
        "state_backing",
        "fsm",
        "v907_verify",
        "bridge_diff",
        "subscribe_loop",
        "anchor_emitter",
        "svid_workload_identity",
        "federation_resolver",
    ]


def test_16_stage_1_emits_ten_log_sink_lines(clean_wakir_env) -> None:
    """log_sink captures one JSON line per decision (10 total)."""
    _, log_text = _drive_stage_1()
    lines = [ln for ln in log_text.splitlines() if ln.strip()]
    assert len(lines) == 10
    # Each line is a backend-decision JSON record.
    for ln in lines:
        rec = json.loads(ln)
        assert rec["msg"] == "backend-decision"
    # The tail record domain is bridge_audit_writer.
    assert json.loads(lines[-1])["domain"] == "bridge_audit_writer"


# ---------------------------------------------------------------------------
# 3. Manifest / pin-pack consistency.
# ---------------------------------------------------------------------------


def test_17_manifest_declares_ten_record_inventory(manifest_text: str) -> None:
    """Manifest §1 mentions the 10th record by component slug."""
    assert "bridge-audit-writer" in manifest_text
    # And declares the new image tag at the top.
    assert "0.5.1-pre-cutover" in manifest_text
    # The previously-held-back paragraph from 0.5.0 §5 has been
    # superseded by a wire-in closeout (§2.5 in 0.5.1).
    assert "held back" in manifest_text
    assert "no longer held back" in manifest_text


def test_18_legacy_manifest_present(  # noqa: D401
) -> None:
    """The Tag-45 0.5.0 historical anchor remains on disk for the
    Doppelbetrieb regression-comparison baseline.
    """
    assert LEGACY_MANIFEST_PATH.is_file(), (
        "0.5.0-pre-cutover manifest removed; the Doppelbetrieb "
        "regression-baseline requires its byte-stable retention."
    )
    assert LEGACY_PIN_PACK_PATH.is_file(), (
        "0.5.0-pre-cutover pin pack removed; the Doppelbetrieb "
        "regression-baseline requires its byte-stable retention."
    )


def test_19_pin_pack_wires_bridge_audit_writer(pin_pack: dict) -> None:
    """Pin-pack now lists ``persona-engine-bridge-audit-writer`` in
    ``boot_wired_crates`` at record #10, NOT in ``boot_unwired_crates``.
    """
    wired = {c["name"] for c in pin_pack["boot_wired_crates"]}
    unwired = {c["name"] for c in pin_pack["boot_unwired_crates"]}
    assert "persona-engine-bridge-audit-writer" in wired
    assert "persona-engine-bridge-audit-writer" not in unwired

    # And the record number is exactly 10.
    by_name = {
        c["name"]: c["record"]
        for c in pin_pack["boot_wired_crates"]
    }
    assert by_name["persona-engine-bridge-audit-writer"] == 10


def test_20_pin_pack_unwired_count_is_five(pin_pack: dict) -> None:
    """Unwired-crate count dropped from 6 (Tag-45) to 5 (Tag-48)."""
    assert len(pin_pack["boot_unwired_crates"]) == 5


def test_21_pin_pack_bridge_audit_writer_selector_env(pin_pack: dict) -> None:
    """The 10th wired entry pins the canonical selector/binary ENVs."""
    entry = next(
        c
        for c in pin_pack["boot_wired_crates"]
        if c["name"] == "persona-engine-bridge-audit-writer"
    )
    assert entry["selector_env"] == "WAKIR_BRIDGE_AUDIT_WRITER_BACKEND"
    assert entry["binary_env"] == "WAKIR_RUST_BRIDGE_AUDIT_WRITER_BIN"
    assert entry["python_authority"] == (
        "wirelang.persona_engine.bridge_audit_writer"
    )


def test_22_pin_pack_cargo_toml_alignment() -> None:
    """``persona-engine-bridge-audit-writer`` Cargo.toml version is 0.1.0."""
    cargo = (
        CRATES_ROOT
        / "persona-engine-bridge-audit-writer"
        / "Cargo.toml"
    )
    assert cargo.is_file()
    src = cargo.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', src, re.MULTILINE)
    assert match
    assert match.group(1) == "0.1.0"


# ---------------------------------------------------------------------------
# 4. Backward-compat: boot fingerprint extension semantics.
# ---------------------------------------------------------------------------


def _fingerprint(decisions) -> str:
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


def test_23_boot_fingerprint_deterministic_across_runs(
    clean_wakir_env,
) -> None:
    """Two independent boot fan-out replays yield the same fingerprint."""
    a, _ = _drive_stage_1()
    b, _ = _drive_stage_1()
    assert _fingerprint(a) == _fingerprint(b)


def test_24_boot_fingerprint_extends_when_tenth_record_added(
    clean_wakir_env,
) -> None:
    """The Tag-48 10-record fingerprint differs from the Tag-45 9-record
    fingerprint (the 10th 4-tuple at the tail shifts the hash).

    Establishes that the wire-in is *observable* in the fingerprint —
    operators rotating from 0.5.0-pre-cutover to 0.5.1-pre-cutover
    will see the fingerprint shift exactly once at cutover.
    """
    decisions_ten, _ = _drive_stage_1()
    fp_ten = _fingerprint(decisions_ten)
    fp_nine = _fingerprint(decisions_ten[:9])
    assert fp_ten != fp_nine
    assert len(fp_ten) == 64


def test_25_tenth_record_clean_env_signature(clean_wakir_env) -> None:
    """Tag-80 Welle-3 Cutover: clean-env 10th record signature is
    ``(bridge_audit_writer, requested=rust, chosen=python via
    graceful fallback, fallback_reason=binary_missing,
    bin_path=DEFAULT_RUST_*)``. Resolver probes default bin-Pfad
    bevor er fallt."""
    from wirelang.persona_engine.rust_backend_switch import (
        DEFAULT_RUST_BRIDGE_AUDIT_WRITER_BIN,
    )
    decisions, _ = _drive_stage_1()
    tenth = decisions[-1]
    assert tenth.domain == "bridge_audit_writer"
    assert tenth.requested_backend == "rust"
    assert tenth.chosen_backend == "python"  # graceful fallback
    assert tenth.fallback_reason == "binary_missing"
    assert tenth.bin_path == DEFAULT_RUST_BRIDGE_AUDIT_WRITER_BIN
