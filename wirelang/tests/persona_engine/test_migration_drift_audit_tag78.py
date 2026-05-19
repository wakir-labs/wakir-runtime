# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-78 - Engine-Migration-Drift audit hermetic test suite (Selin).

Pins the contract of ``tooling/audit/audit_engine_migration_drift.py``:
the audit-only helper that walks the Python Stage-1 authority surface
+ the Rust Stage-2 plan crate roster + emits a stable JSON drift
envelope. The tests are pure-stdlib + ``tmp_path`` fixtures; no
network, no NATS, no subprocess, no git invocation.

The Tag-78 polish-phase test-count target is >= 15. The current
file ships 18 tests across five lemma-families:

  * F1 - drift-envelope shape stability (top-level keys + sub-shape).
  * F2 - Python-authority scanner counter accuracy.
  * F3 - Rust-crate parity-anchor extraction accuracy.
  * F4 - cross-side drift classification (D3 dimension).
  * F5 - Welle-state-machine drift block (D4 dimension).
  * F6 - CLI exit-code contract on stale-anchor.

Scope discipline (Selin)
------------------------
Audit-only. The tests do NOT exercise any actual migration step, do
NOT mutate the runtime Python authority, do NOT mutate the runtime
Rust workspace, do NOT touch persona-definition files (Aisha-
Domaene), do NOT touch WAT-core (Tomas), do NOT touch identity-
substrate (Reza), do NOT touch container-infra (Kai).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the audit helper importable without installing the repo.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_TOOLING_AUDIT = _REPO_ROOT / "tooling" / "audit"
if str(_TOOLING_AUDIT) not in sys.path:
    sys.path.insert(0, str(_TOOLING_AUDIT))

import audit_engine_migration_drift as drift  # noqa: E402


# ---------------------------------------------------------------- #
# Fixture builders                                                 #
# ---------------------------------------------------------------- #


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _build_python_authority_skeleton(root: Path) -> None:
    """
    Manufacture a *minimal* Python authority skeleton under
    ``<root>/wirelang/persona_engine/`` that contains a representative
    sample of every symbol-kind the audit counts. Each authority file
    is intentionally tiny; the test only validates *that the counter
    fires*, not that it matches the production module's full surface.
    """
    pe = root / "wirelang" / "persona_engine"
    _write(
        pe / "welle_state_producer.py",
        "\n".join([
            "STATUS_PENDING = 'pending'",
            "STATUS_IN_PROGRESS = 'in-progress'",
            "STATUS_SIGNED_OFF = 'signed-off'",
            "STATUS_ROLLED_BACK = 'rolled-back'",
            "DOPPELBETRIEB_SEALED = 'sealed'",
            "SNAPSHOT_RESTORE_VERIFIED = 'restored'",
            "CAPABILITY_TOKEN_ROTATED = 'rotated'",
            "CROSS_SUBSTRATE_PARITY_VERIFIED = 'verified'",
            "FINAL_SEALING_CONFIRMED = 'confirmed'",
            "ROLLBACK_MARKER_AUTHORIZED = 'rollback-authorized'",
            "PHASE_3_COMPLETE_VERIFIED = 'phase-3-complete-verified'",
            "PRE_AUDITOR_GUARDED_WELLEN = frozenset({3, 7})",
            "DOPPELBETRIEB_SEALED_WELLEN = frozenset({2})",
            "SNAPSHOT_RESTORE_GUARDED_WELLEN = frozenset({4})",
            "CAPABILITY_TOKEN_ROTATION_GUARDED_WELLEN = frozenset({5})",
            "CROSS_SUBSTRATE_PARITY_GUARDED_WELLEN = frozenset({6})",
            "FINAL_SEALING_GUARDED_WELLEN = frozenset({7})",
            "VALID_WELLE_NUMBERS = frozenset(range(1, 8))",
            "ALLOWED_TRANSITIONS = frozenset({('pending', 'in-progress')})",
            "class WelleProducerError(RuntimeError): pass",
        ]),
    )
    _write(
        pe / "engine.py",
        "\n".join([
            "def handle_welle_4_signoff_event(): pass",
            "def handle_welle_5_signoff_event(): pass",
            "def handle_welle_rollback_event(): pass",
            "class EnvContractError(RuntimeError): pass",
        ]),
    )
    _write(pe / "engine_async.py", "# async wrappers only, no top-level symbols\n")
    _write(pe / "lifecycle_state_machine.py", "class FsmError(Exception): pass\n")
    _write(pe / "lifecycle_state_machine_canonical.py", "# canonical sibling\n")
    _write(pe / "state_backing.py", "class PersonaStateBackingError(Exception): pass\n")
    _write(pe / "recovery_workflow.py", "# recovery body\n")
    _write(pe / "recovery_workflow_canonical.py", "# recovery canonical\n")
    _write(pe / "v907_verify.py", "# v907 body\n")
    _write(pe / "v907_verify_canonical.py", "# v907 canonical\n")
    _write(pe / "bridge_audit_diff_engine.py", "# diff engine\n")
    _write(pe / "bridge_audit_diff_engine_canonical.py", "# diff engine canonical\n")
    _write(pe / "bridge_audit_writer.py", "# writer body\n")
    _write(pe / "bridge_audit_replay_canonical.py", "# replay canonical\n")
    _write(pe / "nats_subjects.py", "# subjects body\n")
    _write(pe / "nats_subscribe_loop.py", "# subscribe body\n")
    _write(pe / "anchor_emitter.py", "# anchor body\n")
    _write(pe / "svid_workload_identity.py", "# svid body\n")
    _write(pe / "migrate_version.py", "# migrate body\n")
    _write(pe / "migrate_version_canonical.py", "# migrate canonical\n")


def _build_rust_crate_skeleton(root: Path) -> None:
    """
    Manufacture a minimal Rust workspace skeleton that declares
    Python authority anchors for *some* of the authority modules.
    Each crate is just a ``src/lib.rs`` file with a recognisable
    anchor declaration in its header comment.
    """
    crates = root / "wirelang-rust" / "crates"
    _write(
        crates / "persona-engine-fsm" / "src" / "lib.rs",
        "// Schema-parity authority: `wirelang/persona_engine/lifecycle_state_machine.py`\n"
        "// Also references `wirelang.persona_engine.lifecycle_state_machine_canonical`.\n",
    )
    _write(
        crates / "persona-engine-state-backing" / "src" / "lib.rs",
        "//! Mirrors `wirelang/persona_engine/state_backing.py`.\n",
    )
    _write(
        crates / "persona-engine-recovery" / "src" / "lib.rs",
        "//! Sibling of `wirelang/persona_engine/recovery_workflow.py` /\n"
        "//! `wirelang.persona_engine.recovery_workflow_canonical`.\n",
    )
    _write(
        crates / "persona-engine-v907-verify" / "src" / "lib.rs",
        "//! `wirelang/persona_engine/v907_verify.py` parity.\n",
    )
    _write(
        crates / "persona-engine-bridge-diff" / "src" / "lib.rs",
        "//! Rust port of `wirelang.persona_engine.bridge_audit_diff_engine`.\n",
    )
    _write(
        crates / "persona-engine-bridge-audit-writer" / "src" / "lib.rs",
        "// Mirrors `wirelang/persona_engine/bridge_audit_writer.py`.\n",
    )
    _write(
        crates / "persona-engine-bridge-audit-replay" / "src" / "lib.rs",
        "//! `wirelang.persona_engine.bridge_audit_replay_canonical` sibling.\n",
    )
    _write(
        crates / "persona-engine-nats-subjects" / "src" / "lib.rs",
        "// `wirelang/persona_engine/nats_subjects.py` mirror.\n",
    )
    _write(
        crates / "persona-engine-subscribe-loop" / "src" / "lib.rs",
        "// Sibling of `wirelang/persona_engine/nats_subscribe_loop.py`.\n",
    )
    _write(
        crates / "persona-engine-svid-workload-identity" / "src" / "lib.rs",
        "// `wirelang.persona_engine.svid_workload_identity` Rust pendant.\n",
    )
    _write(
        crates / "persona-engine-migrate-version" / "src" / "lib.rs",
        "//! Rust pendant of `wirelang.persona_engine.migrate_version_canonical`.\n",
    )
    # A crate with no anchor declaration at all (smoke).
    _write(
        crates / "persona-engine-loop-latency-bench" / "src" / "lib.rs",
        "// Benchmark harness, no authority anchor.\n",
    )


@pytest.fixture
def hermetic_runtime(tmp_path: Path) -> Path:
    """Compose the minimal Python authority + Rust crate skeleton."""
    _build_python_authority_skeleton(tmp_path)
    _build_rust_crate_skeleton(tmp_path)
    return tmp_path


# ---------------------------------------------------------------- #
# F1 - drift-envelope shape stability                              #
# ---------------------------------------------------------------- #


class TestDriftEnvelopeShape:
    def test_envelope_top_level_keys_are_stable(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        payload = json.loads(env.to_json())
        # Top-level shape is the public contract; ordering is preserved
        # in to_json() (json.dumps sort_keys=False on a dataclasses.asdict
        # ordered dict).
        assert set(payload.keys()) == {
            "audit_id",
            "audit_only",
            "runtime_root",
            "python_authorities",
            "rust_crates",
            "drift_map",
            "welle_state_machine_drift",
            "summary",
        }

    def test_audit_id_is_tag78_literal(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        assert env.audit_id == "tag-78-engine-migration-drift-audit"

    def test_audit_only_flag_is_true(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        assert env.audit_only is True

    def test_envelope_to_json_round_trips(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        as_text = env.to_json()
        parsed = json.loads(as_text)
        # Confirm a few canary fields survive the round-trip unchanged.
        assert parsed["audit_id"] == env.audit_id
        assert parsed["summary"]["python_authorities_total"] == len(env.python_authorities)


# ---------------------------------------------------------------- #
# F2 - Python-authority scanner counter accuracy                   #
# ---------------------------------------------------------------- #


class TestPythonAuthorityScanner:
    def test_welle_state_producer_status_constant_count(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        wsp = next(a for a in env.python_authorities
                   if a.module == "wirelang/persona_engine/welle_state_producer.py")
        # Fixture writes 4 STATUS_* constants.
        assert wsp.symbol_kinds.status_constants == 4

    def test_welle_state_producer_marker_literal_count(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        wsp = next(a for a in env.python_authorities
                   if a.module == "wirelang/persona_engine/welle_state_producer.py")
        # Fixture writes 12 lines whose left-hand-side prefix matches the
        # catalogued marker-literal regex (DOPPELBETRIEB_*, SNAPSHOT_*,
        # CAPABILITY_TOKEN_*, CROSS_SUBSTRATE_*, FINAL_SEALING_*,
        # ROLLBACK_MARKER_*, PHASE_3_COMPLETE_*). Both the bare marker
        # constants (e.g. DOPPELBETRIEB_SEALED) and the marker-keyed
        # set constants (e.g. DOPPELBETRIEB_SEALED_WELLEN) match the
        # prefix-based regex; that is by design -- the regex is a
        # *family-membership* counter, not a deduplicated marker counter.
        assert wsp.symbol_kinds.marker_literals == 12

    def test_welle_state_producer_guarded_welle_sets_count(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        wsp = next(a for a in env.python_authorities
                   if a.module == "wirelang/persona_engine/welle_state_producer.py")
        # 5 *_GUARDED_WELLEN sets in the fixture (PRE_AUDITOR,
        # SNAPSHOT_RESTORE, CAPABILITY_TOKEN_ROTATION,
        # CROSS_SUBSTRATE_PARITY, FINAL_SEALING). DOPPELBETRIEB has its
        # set named DOPPELBETRIEB_SEALED_WELLEN (no ``_GUARDED_`` infix)
        # which intentionally matches the marker_literals regex instead.
        assert wsp.symbol_kinds.guarded_welle_sets == 5

    def test_engine_py_handler_function_count(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        eng = next(a for a in env.python_authorities
                   if a.module == "wirelang/persona_engine/engine.py")
        # Fixture writes 3 handle_*_event functions.
        assert eng.symbol_kinds.handler_functions == 3

    def test_absent_module_returns_zero_counts(self, tmp_path: Path) -> None:
        # No skeleton at all: every authority is absent.
        env = drift.run_audit(runtime_root=tmp_path)
        assert all(not a.present for a in env.python_authorities)
        assert all(a.symbol_total == 0 for a in env.python_authorities)
        assert env.summary.python_authorities_present == 0


# ---------------------------------------------------------------- #
# F3 - Rust-crate parity-anchor extraction                         #
# ---------------------------------------------------------------- #


class TestRustCrateAnchorExtractor:
    def test_path_form_anchor_is_extracted(self) -> None:
        text = "// Schema-parity authority: `wirelang/persona_engine/foo.py`"
        anchors = drift.extract_python_anchors_from_rust(text)
        assert "wirelang/persona_engine/foo.py" in anchors

    def test_module_form_anchor_is_extracted(self) -> None:
        text = "//! Mirrors `wirelang.persona_engine.bar_canonical`."
        anchors = drift.extract_python_anchors_from_rust(text)
        assert "wirelang/persona_engine/bar_canonical.py" in anchors

    def test_module_form_with_symbol_suffix_strips_to_module(self) -> None:
        # ``wirelang.persona_engine.foo.SomeSymbol`` -> ``wirelang/persona_engine/foo.py``
        text = "// `wirelang.persona_engine.subscribe_ack.AckRecord` parity."
        anchors = drift.extract_python_anchors_from_rust(text)
        assert "wirelang/persona_engine/subscribe_ack.py" in anchors

    def test_persona_engine_crate_enumeration_skips_non_persona_engine(
        self, hermetic_runtime: Path
    ) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        for c in env.rust_crates:
            assert c.crate.startswith("persona-engine-"), (
                f"non-persona-engine crate leaked: {c.crate}"
            )

    def test_crate_without_anchor_reports_zero(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        bench = next(c for c in env.rust_crates
                     if c.crate == "persona-engine-loop-latency-bench")
        assert bench.lib_rs_present is True
        assert bench.declared_anchor_count == 0


# ---------------------------------------------------------------- #
# F4 - cross-side drift classification                             #
# ---------------------------------------------------------------- #


class TestDriftClassification:
    def test_lifecycle_authority_pendant_present(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        e = next(e for e in env.drift_map
                 if e.python_authority == "wirelang/persona_engine/lifecycle_state_machine.py")
        assert e.drift_class == "rust-pendant-present"
        assert "persona-engine-fsm" in e.rust_pendants

    def test_anchor_emitter_pendant_absent(self, hermetic_runtime: Path) -> None:
        # The fixture's anchor_emitter Python authority has no Rust pendant
        # crate that declares it. Mirrors the runtime-tip reality at Tag-78.
        env = drift.run_audit(runtime_root=hermetic_runtime)
        e = next(e for e in env.drift_map
                 if e.python_authority == "wirelang/persona_engine/anchor_emitter.py")
        assert e.drift_class == "rust-pendant-absent"
        assert e.rust_pendants == ()

    def test_no_stale_anchor_on_clean_skeleton(self, hermetic_runtime: Path) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        assert env.summary.stale_anchor_count == 0
        assert all(e.drift_class != "stale-anchor" for e in env.drift_map)

    def test_stale_anchor_fires_when_rust_references_unknown_authority(
        self, hermetic_runtime: Path
    ) -> None:
        # Inject a Rust crate that references an authority module that
        # exists neither in the catalogue nor on disk.
        crates = hermetic_runtime / "wirelang-rust" / "crates"
        _write(
            crates / "persona-engine-mystery" / "src" / "lib.rs",
            "// Mirrors `wirelang/persona_engine/does_not_exist.py`.\n",
        )
        env = drift.run_audit(runtime_root=hermetic_runtime)
        stale = [e for e in env.drift_map if e.drift_class == "stale-anchor"]
        assert len(stale) >= 1
        assert any(
            e.python_authority == "wirelang/persona_engine/does_not_exist.py"
            for e in stale
        )


# ---------------------------------------------------------------- #
# F5 - Welle-state-machine drift block (D4)                        #
# ---------------------------------------------------------------- #


class TestWelleStateMachineDriftBlock:
    def test_welle_state_machine_drift_class_is_absent_expected(
        self, hermetic_runtime: Path
    ) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        ws = env.welle_state_machine_drift
        assert ws.python_authority == "wirelang/persona_engine/welle_state_producer.py"
        assert ws.python_authority_present is True
        assert ws.rust_pendant_declared is False
        assert ws.expected_absent is True
        assert ws.drift_class == "rust-pendant-absent-expected"

    def test_welle_state_machine_pendant_flip_when_rust_anchor_added(
        self, hermetic_runtime: Path
    ) -> None:
        # Inject a Rust crate that declares the welle-state-producer as
        # its parity anchor. This is the hypothetical Tag-N+ Stage-2 plan
        # realisation.
        crates = hermetic_runtime / "wirelang-rust" / "crates"
        _write(
            crates / "persona-engine-welle-state-producer" / "src" / "lib.rs",
            "//! Mirrors `wirelang/persona_engine/welle_state_producer.py`.\n",
        )
        env = drift.run_audit(runtime_root=hermetic_runtime)
        ws = env.welle_state_machine_drift
        assert ws.rust_pendant_declared is True
        assert ws.rust_pendant_crate == "persona-engine-welle-state-producer"
        assert ws.drift_class == "rust-pendant-present"
        # The summary flag flips in lockstep.
        assert env.summary.welle_state_pendant_present is True

    def test_welle_state_machine_carries_python_symbol_counts(
        self, hermetic_runtime: Path
    ) -> None:
        env = drift.run_audit(runtime_root=hermetic_runtime)
        ws = env.welle_state_machine_drift
        # The fixture's welle_state_producer has 4 status constants,
        # 12 marker-family literals (including marker-keyed set names),
        # 5 *_GUARDED_WELLEN sets, 1 transition table -- see the
        # F2 counter tests for the breakdown.
        assert ws.python_status_constants == 4
        assert ws.python_marker_literals == 12
        assert ws.python_guarded_welle_sets == 5
        assert ws.python_transition_tables == 1


# ---------------------------------------------------------------- #
# F6 - CLI exit-code contract                                      #
# ---------------------------------------------------------------- #


class TestCliExitCodeContract:
    def test_main_exits_zero_on_no_stale_anchor(
        self, hermetic_runtime: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        rc = drift.main(["--runtime-root", str(hermetic_runtime)])
        assert rc == 0
        out = capsys.readouterr().out
        envelope = json.loads(out)
        assert envelope["summary"]["stale_anchor_count"] == 0

    def test_main_exits_one_on_stale_anchor(
        self, hermetic_runtime: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        crates = hermetic_runtime / "wirelang-rust" / "crates"
        _write(
            crates / "persona-engine-mystery" / "src" / "lib.rs",
            "// Mirrors `wirelang/persona_engine/ghost.py`.\n",
        )
        rc = drift.main(["--runtime-root", str(hermetic_runtime)])
        assert rc == 1
        out = capsys.readouterr().out
        envelope = json.loads(out)
        assert envelope["summary"]["stale_anchor_count"] >= 1
