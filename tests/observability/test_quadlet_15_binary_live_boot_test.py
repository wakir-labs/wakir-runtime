# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic invariants for the Tag-52 Quadlet-15-Binary Live-Boot-Test.

Tag-52 ships the runtime-boot axis of the 15-binary substrate: a
sandbox-stub simulator that exercises 5 phases per binary
(``quadlet_load``, ``cosign_verify``, ``start``, ``health_check``,
``exit_code``) deterministically, in-process, without touching
``podman`` / ``cosign`` / ``crane`` / ``systemctl``. Live verification
is Operator-Hand only per ``feedback_sandbox_host_trennung.md`` +
ADR-0051; this test surface reads files on disk only.

Sibling tests
-------------

  * ``tests/infra/test_tag45_quadlet_cosign_15_binary_substrate.py``
    -- Tag-45 substrate-shape invariants (12 tests).
  * ``tests/observability/test_cosign_keyless_oidc_drift_probe.py``
    -- Tag-47 OIDC-drift invariants.
  * ``tests/observability/test_generate_15_binary_sbom.py``
    -- Tag-48 SBOM-generator invariants.

Test-Vector index
-----------------

  * ``TV-T52-01`` Tag-45 binary inventory mirrored (15 entries, order).
  * ``TV-T52-02`` Carrier vs dedicated split mirrored (11 + 4 = 15).
  * ``TV-T52-03`` Five canonical phases declared in order.
  * ``TV-T52-04`` Inventory classification is total (every binary
                  classified, no "unknown" emitted).
  * ``TV-T52-05`` Aggregate GREEN against real on-disk substrate.
  * ``TV-T52-06`` Per-binary 5/5 phase verdicts emitted.
  * ``TV-T52-07`` Boot-fingerprint deterministic across re-evaluation.
  * ``TV-T52-08`` Boot-fingerprints distinct across binaries.
  * ``TV-T52-09`` cosign_verify RED on missing policy entry.
  * ``TV-T52-10`` health_check RED on non-canonical in_image_path.
  * ``TV-T52-11`` exit_code cascades RED from any earlier-phase RED.
  * ``TV-T52-12`` quadlet_load RED on missing Quadlet unit.
  * ``TV-T52-13`` Live-mode raises NotImplementedError.
  * ``TV-T52-14`` JSON envelope schema-shape canonical.
  * ``TV-T52-15`` Prometheus textfile carries all required gauges.
  * ``TV-T52-16`` Mira-Notify payload empty on GREEN aggregate.

-- Kai
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = (
    REPO_ROOT
    / "scripts"
    / "observability"
    / "quadlet-15-binary-live-boot-test.py"
)
POLICY_PATH = REPO_ROOT / "policies" / "cosign-policy-phase-3b.yaml"


def _load_module():
    """Load the live-boot script as a module (path has a hyphen)."""
    spec = importlib.util.spec_from_file_location(
        "quadlet_15_binary_live_boot_test", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def mod():
    return _load_module()


@pytest.fixture(scope="module")
def policy_index(mod):
    return mod.load_policy(POLICY_PATH)


# ---------------------------------------------------------------------------
# TV-T52-01
# ---------------------------------------------------------------------------


def test_tv_t52_01_inventory_size_and_order(mod):
    """Inventory mirrors Tag-45 substrate: 15 entries, canonical order."""
    inv = mod.TAG45_BINARY_INVENTORY
    assert len(inv) == 15
    # First and last entries pin the order anchors.
    assert inv[0] == "recovery"
    assert inv[-1] == "migrate-version"
    # The two Tag-45 additions are the last two entries.
    assert inv[-2] == "bridge-audit-replay"
    assert inv[-1] == "migrate-version"


# ---------------------------------------------------------------------------
# TV-T52-02
# ---------------------------------------------------------------------------


def test_tv_t52_02_carrier_vs_dedicated_split(mod):
    """11 carrier + 4 dedicated = 15 inventory entries, no overlap."""
    carrier = set(mod.CARRIER_IMAGE_BINARIES)
    dedicated = set(mod.DEDICATED_IMAGE_BINARIES)
    assert len(carrier) == 11
    assert len(dedicated) == 4
    assert carrier.isdisjoint(dedicated)
    union = carrier | dedicated
    assert union == set(mod.TAG45_BINARY_INVENTORY)


# ---------------------------------------------------------------------------
# TV-T52-03
# ---------------------------------------------------------------------------


def test_tv_t52_03_five_canonical_phases_in_order(mod):
    """The 5 canonical boot phases are declared in canonical order."""
    expected = (
        "quadlet_load",
        "cosign_verify",
        "start",
        "health_check",
        "exit_code",
    )
    assert mod.PHASES == expected


# ---------------------------------------------------------------------------
# TV-T52-04
# ---------------------------------------------------------------------------


def test_tv_t52_04_classification_total(mod):
    """Every Tag-45 inventory entry classifies as carrier or dedicated."""
    for binary_name in mod.TAG45_BINARY_INVENTORY:
        kind = mod.classify_image_kind(binary_name)
        assert kind in ("carrier", "dedicated"), (
            f"{binary_name} classified as {kind}"
        )
    # And a known-bad name surfaces as "unknown".
    assert mod.classify_image_kind("not-a-real-binary") == "unknown"


# ---------------------------------------------------------------------------
# TV-T52-05
# ---------------------------------------------------------------------------


def test_tv_t52_05_aggregate_green_against_real_substrate(mod, policy_index):
    """Running the live-boot test against the real repo yields GREEN."""
    verdict = mod.evaluate_inventory(
        policy_index, REPO_ROOT, mode="sandbox-stub"
    )
    assert verdict.overall_green
    assert verdict.binary_count == 15
    assert verdict.green_count == 15
    assert verdict.red_count == 0


# ---------------------------------------------------------------------------
# TV-T52-06
# ---------------------------------------------------------------------------


def test_tv_t52_06_per_binary_phase_count(mod, policy_index):
    """Each binary emits exactly 5 phase verdicts in canonical order."""
    verdict = mod.evaluate_inventory(
        policy_index, REPO_ROOT, mode="sandbox-stub"
    )
    for b in verdict.per_binary:
        assert len(b.phases) == 5
        emitted_phase_names = tuple(p.phase for p in b.phases)
        assert emitted_phase_names == mod.PHASES


# ---------------------------------------------------------------------------
# TV-T52-07
# ---------------------------------------------------------------------------


def test_tv_t52_07_boot_fingerprint_deterministic(mod, policy_index):
    """Two evaluations produce byte-equal fingerprints per binary."""
    v1 = mod.evaluate_inventory(policy_index, REPO_ROOT, mode="sandbox-stub")
    v2 = mod.evaluate_inventory(policy_index, REPO_ROOT, mode="sandbox-stub")
    assert len(v1.per_binary) == len(v2.per_binary)
    for a, b in zip(v1.per_binary, v2.per_binary):
        assert a.boot_fingerprint == b.boot_fingerprint
        # And non-empty.
        assert len(a.boot_fingerprint) == 64  # SHA-256 hex.


# ---------------------------------------------------------------------------
# TV-T52-08
# ---------------------------------------------------------------------------


def test_tv_t52_08_boot_fingerprints_distinct(mod, policy_index):
    """All 15 fingerprints are distinct (no accidental collisions)."""
    verdict = mod.evaluate_inventory(
        policy_index, REPO_ROOT, mode="sandbox-stub"
    )
    fps = [b.boot_fingerprint for b in verdict.per_binary]
    assert len(set(fps)) == len(fps)


# ---------------------------------------------------------------------------
# TV-T52-09
# ---------------------------------------------------------------------------


def test_tv_t52_09_cosign_verify_red_on_missing_entry(mod):
    """A missing policy entry surfaces RED on the cosign_verify phase."""
    result = mod.evaluate_cosign_verify("phantom-binary", None)
    assert result.phase == "cosign_verify"
    assert not result.green
    assert "no policy entry" in result.detail


# ---------------------------------------------------------------------------
# TV-T52-10
# ---------------------------------------------------------------------------


def test_tv_t52_10_health_check_red_on_non_canonical_path(mod):
    """A non-canonical ``in_image_path`` surfaces RED on health_check."""
    bad_entry = {
        "in_image_path": "/usr/local/bin/wakir-persona-engine-recovery",
    }
    result = mod.evaluate_health_check("recovery", bad_entry)
    assert not result.green
    assert "does not start with" in result.detail

    # Basename mismatch is also RED.
    basename_mismatch = {
        "in_image_path": "/opt/wakir/bin/wakir-persona-engine-wrong-name",
    }
    result2 = mod.evaluate_health_check("recovery", basename_mismatch)
    assert not result2.green
    assert "basename mismatch" in result2.detail


# ---------------------------------------------------------------------------
# TV-T52-11
# ---------------------------------------------------------------------------


def test_tv_t52_11_exit_code_cascades_red(mod):
    """Any earlier-phase RED cascades to exit_code RED."""
    PhaseResult = mod.PhaseResult
    earlier = (
        PhaseResult(phase="quadlet_load", green=True, detail="ok"),
        PhaseResult(phase="cosign_verify", green=False, detail="missing"),
        PhaseResult(phase="start", green=True, detail="ok"),
        PhaseResult(phase="health_check", green=True, detail="ok"),
    )
    result = mod.evaluate_exit_code(earlier)
    assert not result.green
    assert "earlier phase(s) RED" in result.detail
    assert "cosign_verify" in result.detail

    # And all-green earlier phases produce GREEN exit_code.
    all_green = tuple(
        PhaseResult(phase=p, green=True, detail="ok")
        for p in ("quadlet_load", "cosign_verify", "start", "health_check")
    )
    result_ok = mod.evaluate_exit_code(all_green)
    assert result_ok.green
    assert "simulated exit code = 0" in result_ok.detail


# ---------------------------------------------------------------------------
# TV-T52-12
# ---------------------------------------------------------------------------


def test_tv_t52_12_quadlet_load_red_on_missing_unit(mod, tmp_path):
    """A missing Quadlet unit surfaces RED on quadlet_load."""
    # Empty repo root -> no quadlet/ dir -> phase RED.
    result = mod.evaluate_quadlet_load(
        "recovery", "carrier", tmp_path
    )
    assert not result.green
    assert "not found" in result.detail

    # Wrong image_kind also RED.
    result_unknown = mod.evaluate_quadlet_load(
        "phantom", "unknown", REPO_ROOT
    )
    assert not result_unknown.green
    assert "unknown image_kind" in result_unknown.detail


# ---------------------------------------------------------------------------
# TV-T52-13
# ---------------------------------------------------------------------------


def test_tv_t52_13_live_mode_raises_not_implemented(mod):
    """``--mode=live`` raises NotImplementedError (Operator-Hand only)."""
    with pytest.raises(NotImplementedError) as exc:
        mod.main(
            [
                "--policy",
                str(POLICY_PATH),
                "--repo-root",
                str(REPO_ROOT),
                "--mode",
                "live",
            ]
        )
    msg = str(exc.value)
    assert "Operator-Hand" in msg


# ---------------------------------------------------------------------------
# TV-T52-14
# ---------------------------------------------------------------------------


def test_tv_t52_14_envelope_schema_shape(mod, policy_index, tmp_path):
    """JSON envelope carries the canonical schema + required keys."""
    verdict = mod.evaluate_inventory(
        policy_index, REPO_ROOT, mode="sandbox-stub"
    )
    envelope = mod.render_envelope(verdict)
    assert envelope["schema"] == "wakir-runtime/quadlet-live-boot-verdict@1"
    assert envelope["tool"] == "wakir-runtime-quadlet-live-boot-test"
    assert envelope["tool_version"] == "tag-52"
    assert envelope["binary_count"] == 15
    assert envelope["aggregate_verdict"] == "GREEN"
    assert len(envelope["per_binary"]) == 15
    # Each per-binary entry carries the 5 phases in canonical order.
    for entry in envelope["per_binary"]:
        assert "binary_name" in entry
        assert "image_kind" in entry
        assert "boot_fingerprint" in entry
        assert "verdict" in entry
        assert len(entry["phases"]) == 5
        phase_names = [p["phase"] for p in entry["phases"]]
        assert tuple(phase_names) == mod.PHASES

    # JSON-serialisable, byte-stable.
    j1 = json.dumps(envelope, sort_keys=True, indent=2)
    j2 = json.dumps(
        mod.render_envelope(verdict), sort_keys=True, indent=2
    )
    assert j1 == j2


# ---------------------------------------------------------------------------
# TV-T52-15
# ---------------------------------------------------------------------------


def test_tv_t52_15_textfile_carries_all_gauges(mod, policy_index):
    """Prometheus textfile carries the 3 canonical gauge metrics."""
    verdict = mod.evaluate_inventory(
        policy_index, REPO_ROOT, mode="sandbox-stub"
    )
    textfile = mod.render_textfile(verdict)
    assert "wakir_quadlet_live_boot_phase_green" in textfile
    assert "wakir_quadlet_live_boot_binary_green" in textfile
    assert "wakir_quadlet_live_boot_aggregate_green" in textfile
    # Aggregate gauge is GREEN -> 1.0.
    assert "wakir_quadlet_live_boot_aggregate_green 1.0" in textfile
    # 15 binaries x 5 phases = 75 phase-gauge lines.
    phase_lines = [
        l
        for l in textfile.splitlines()
        if l.startswith("wakir_quadlet_live_boot_phase_green{")
    ]
    assert len(phase_lines) == 75
    # 15 binary-overall gauges.
    binary_lines = [
        l
        for l in textfile.splitlines()
        if l.startswith("wakir_quadlet_live_boot_binary_green{")
    ]
    assert len(binary_lines) == 15


# ---------------------------------------------------------------------------
# TV-T52-16
# ---------------------------------------------------------------------------


def test_tv_t52_16_mira_notify_empty_on_green(mod, policy_index):
    """Mira-Notify payload is None when the aggregate is GREEN."""
    verdict = mod.evaluate_inventory(
        policy_index, REPO_ROOT, mode="sandbox-stub"
    )
    assert verdict.overall_green
    notify = mod.render_mira_notify(verdict)
    assert notify is None


# ---------------------------------------------------------------------------
# TV-T52-17 -- bonus: synthetic RED produces non-empty Mira-Notify.
# ---------------------------------------------------------------------------


def test_tv_t52_17_mira_notify_populated_on_red(mod):
    """A synthetic RED aggregate produces a populated Mira-Notify."""
    PhaseResult = mod.PhaseResult
    BinaryBootVerdict = mod.BinaryBootVerdict
    AggregateVerdict = mod.AggregateVerdict

    red_phases = (
        PhaseResult("quadlet_load", True, "ok"),
        PhaseResult("cosign_verify", False, "missing keys: purpose"),
        PhaseResult("start", True, "ok"),
        PhaseResult("health_check", True, "ok"),
        PhaseResult("exit_code", False, "earlier phase(s) RED"),
    )
    red_binary = BinaryBootVerdict(
        binary_name="recovery",
        image_kind="carrier",
        phases=red_phases,
        boot_fingerprint="0" * 64,
        overall_green=False,
    )
    agg = AggregateVerdict(
        mode="sandbox-stub",
        binary_count=1,
        green_count=0,
        red_count=1,
        per_binary=(red_binary,),
        overall_green=False,
    )
    notify = mod.render_mira_notify(agg)
    assert notify is not None
    assert notify["event_type"] == "wakir.quadlet-live-boot.drift"
    assert notify["red_count"] == 1
    assert len(notify["red_binaries"]) == 1
    rb = notify["red_binaries"][0]
    assert rb["binary"] == "recovery"
    red_phase_names = [p["phase"] for p in rb["red_phases"]]
    assert "cosign_verify" in red_phase_names
    assert "exit_code" in red_phase_names


# ---------------------------------------------------------------------------
# TV-T52-18 -- bonus: CLI exit code on GREEN is 0.
# ---------------------------------------------------------------------------


def test_tv_t52_18_cli_exit_code_green(mod, tmp_path):
    """End-to-end CLI invocation returns exit 0 on GREEN substrate."""
    out_json = tmp_path / "envelope.json"
    out_text = tmp_path / "metrics.prom"
    out_md = tmp_path / "summary.md"
    out_mira = tmp_path / "mira-notify.json"
    rc = mod.main(
        [
            "--policy",
            str(POLICY_PATH),
            "--repo-root",
            str(REPO_ROOT),
            "--out-json",
            str(out_json),
            "--out-textfile",
            str(out_text),
            "--out-markdown",
            str(out_md),
            "--out-mira-notify",
            str(out_mira),
        ]
    )
    assert rc == 0
    assert out_json.exists()
    assert out_text.exists()
    assert out_md.exists()
    assert out_mira.exists()
    # GREEN aggregate -> empty Mira-Notify file.
    assert out_mira.read_text() == ""
    # Envelope round-trips.
    envelope = json.loads(out_json.read_text())
    assert envelope["aggregate_verdict"] == "GREEN"
