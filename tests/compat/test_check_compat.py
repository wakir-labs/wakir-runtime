# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``tooling/compat/check_compat.py``.

Mock checkouts are assembled under ``tmp_path``; nothing is cloned and
no network is touched. Levels that need ``wakir_verify`` skip when the
package is not installed (the CI gate installs it from the clone).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

pytest.importorskip("rfc8785")
pytest.importorskip("jsonschema")
agg = pytest.importorskip("wat.merkle.aggregator")
agg_cli = pytest.importorskip("wat.cmd.aggregator_cli")

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLING = REPO_ROOT / "tooling" / "compat"
REAL_SCHEMAS = REPO_ROOT / "wirelang" / "schemas"

HOUR = "2026-05-17T12"
TODAY = dt.date(2026, 9, 11)
TRACKING = "https://github.com/wakir-labs/wakir-runtime/pull/999"


def _load(name: str):
    if str(TOOLING) not in sys.path:
        sys.path.insert(0, str(TOOLING))
    spec = importlib.util.spec_from_file_location(name, TOOLING / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


cc = _load("check_compat")
allow = sys.modules["compat_allowlist"]


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _write(path: Path, doc, **dump_kwargs) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, **dump_kwargs) + "\n", encoding="utf-8")
    return path


def _leaf(i: int, payload_hash: str | None = None) -> dict:
    return {
        "event_id": f"{i:032x}",
        "time": f"2026-05-17T12:0{i}:00Z",
        "payload_hash": payload_hash or f"{i + 0x10:064x}",
        "capability_token_hash": "0" * 64,
    }


def _proof_doc(leaf_bytes, index, root) -> dict:
    siblings = agg.merkle_proof(leaf_bytes, index)
    return {
        "schema": cc.PROOF_SCHEMA_ID,
        "manifest_version": agg_cli.MANIFEST_VERSION,
        "hour": HOUR,
        "merkle_root": root.hex(),
        "leaf_hash": leaf_bytes[index].hex(),
        "leaf_index": index,
        "leaf_count": len(leaf_bytes),
        "event_id": f"{index:032x}",
        "siblings": [{"hash": h.hex(), "side": side} for h, side in siblings],
    }


def make_vector(vector_id: str, leaves: list[dict], *, tamper: bool = False, with_proofs: bool = True) -> dict:
    leaf_bytes = [agg.compute_leaf_hash(**leaf) for leaf in leaves]
    root, levels = agg.build_merkle_tree(leaf_bytes)
    vec = {
        "schema": cc.VECTOR_SCHEMA_ID,
        "vector_id": vector_id,
        "leaves": leaves,
        "leaf_hashes": [b.hex() for b in leaf_bytes],
        "levels": [[n.hex() for n in level] for level in levels],
        "merkle_root": root.hex(),
        "expected": [{"leaf_index": i, "verified": True} for i in range(len(leaf_bytes))],
    }
    if with_proofs:
        vec["proofs"] = [_proof_doc(leaf_bytes, i, root) for i in range(len(leaf_bytes))]
    if tamper:
        bad = dict(leaves[1], payload_hash="f" * 64)
        vec["tampered"] = {
            "leaf_index": 1,
            "leaf": bad,
            "leaf_hash": agg.compute_leaf_hash(**bad).hex(),
            "proof": _proof_doc(leaf_bytes, 1, root),
            "expected_verified": False,
        }
    return vec


SIMPLE_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.invalid/simple/1",
    "description": "runtime prose",
    "x-spdx-license-identifier": "runtime-licence",
    "type": "object",
    "properties": {"mode": {"type": "string", "enum": ["a", "b"], "description": "nested"}},
}


@pytest.fixture
def repos(tmp_path: Path):
    """Mock runtime + protocol checkouts plus a demo-proof workdir."""
    runtime = tmp_path / "runtime"
    protocol = tmp_path / "protocol"
    demo = tmp_path / "demo"

    rt_schemas = runtime / cc.RUNTIME_SCHEMA_DIR
    pr_schemas = protocol / cc.PROTOCOL_SCHEMA_DIR
    rt_schemas.mkdir(parents=True)
    pr_schemas.mkdir(parents=True)

    # Real manifest + inclusion-proof schemas on both sides (needed by
    # the manifest / proof levels); protocol side re-indented with a
    # different licence header and prose to prove canonicalisation.
    for name in (cc.MANIFEST_SCHEMA_FILE, cc.PROOF_SCHEMA_FILE):
        doc = json.loads((REAL_SCHEMAS / name).read_text(encoding="utf-8"))
        shutil.copy(REAL_SCHEMAS / name, rt_schemas / name)
        other = dict(doc)
        other["x-spdx-license-identifier"] = "protocol-licence"
        other["description"] = "protocol prose"
        _write(pr_schemas / name, other, indent=4)

    _write(rt_schemas / "simple.json", SIMPLE_SCHEMA, separators=(",", ":"))
    proto_simple = json.loads(json.dumps(SIMPLE_SCHEMA))
    proto_simple["x-spdx-license-identifier"] = "protocol-licence"
    proto_simple["description"] = "protocol prose"
    proto_simple["properties"]["mode"].pop("description")
    _write(pr_schemas / "simple.json", proto_simple, indent=2)

    vectors = protocol / cc.PROTOCOL_VECTOR_DIR
    _write(vectors / "vector-1.json", make_vector("vector-1", [_leaf(1)]))
    _write(vectors / "vector-2.json", make_vector("vector-2", [_leaf(1), _leaf(2), _leaf(3)]))
    _write(vectors / "vector-3.json", make_vector("vector-3", [_leaf(1), _leaf(2), _leaf(3)], tamper=True))

    events = [_leaf(1), _leaf(2), _leaf(3)]
    manifest = agg_cli._build_manifest_object(hour_slot=HOUR, events=events, build_time="2026-09-11T00:00:00Z")
    _write(demo / HOUR / "manifest.json", manifest, indent=2)
    leaf_bytes = [bytes.fromhex(e["leaf_hash"]) for e in manifest["leaves"]]
    proof = _proof_doc(leaf_bytes, 1, bytes.fromhex(manifest["merkle_root"]))
    proof["event_id"] = manifest["leaves"][1]["event_id"]
    _write(demo / "proof.json", proof, indent=2)

    return {"runtime": runtime, "protocol": protocol, "demo": demo, "allowlist": tmp_path / "allow.json"}


def _run(repos, **overrides):
    kwargs = dict(
        runtime_root=repos["runtime"],
        protocol_root=repos["protocol"],
        verify_root=None,
        demo_workdir=repos["demo"],
        allowlist_path=repos["allowlist"],
        today=TODAY,
    )
    kwargs.update(overrides)
    return cc.run(**kwargs)


def _by_subject(findings, level=None):
    return {f.subject: f for f in findings if level is None or f.level == level}


# ---------------------------------------------------------------------------
# Schema level (no wakir_verify needed)
# ---------------------------------------------------------------------------


def test_schema_level_green_after_canonicalisation(repos):
    used: set[str] = set()
    findings = cc.check_schemas(repos["runtime"], repos["protocol"], {}, used)
    statuses = {f.subject: f.status for f in findings}
    assert statuses == {
        "wirelang/schemas/simple.json": cc.STATUS_OK,
        f"wirelang/schemas/{cc.MANIFEST_SCHEMA_FILE}": cc.STATUS_OK,
        f"wirelang/schemas/{cc.PROOF_SCHEMA_FILE}": cc.STATUS_OK,
    }
    assert used == set()


def test_schema_level_enum_change_in_protocol_is_red(repos):
    path = repos["protocol"] / cc.PROTOCOL_SCHEMA_DIR / "simple.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["properties"]["mode"]["enum"] = ["a", "b", "c"]
    _write(path, doc)
    findings = _by_subject(cc.check_schemas(repos["runtime"], repos["protocol"], {}, set()))
    finding = findings["wirelang/schemas/simple.json"]
    assert finding.status == cc.STATUS_FAIL
    assert "canonical drift" in finding.detail


def test_schema_level_enum_change_in_runtime_is_red(repos):
    path = repos["runtime"] / cc.RUNTIME_SCHEMA_DIR / "simple.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["properties"]["mode"]["enum"] = ["a"]
    _write(path, doc)
    findings = _by_subject(cc.check_schemas(repos["runtime"], repos["protocol"], {}, set()))
    assert findings["wirelang/schemas/simple.json"].status == cc.STATUS_FAIL


def test_schema_level_missing_counterpart_and_unmirrored_extra(repos):
    (repos["protocol"] / cc.PROTOCOL_SCHEMA_DIR / "simple.json").unlink()
    _write(repos["protocol"] / cc.PROTOCOL_SCHEMA_DIR / "brand-new.json", {"type": "object"})
    findings = _by_subject(cc.check_schemas(repos["runtime"], repos["protocol"], {}, set()))
    assert findings["wirelang/schemas/simple.json"].status == cc.STATUS_FAIL
    assert findings["wakir_protocol/schemas/brand-new.json"].status == cc.STATUS_WARN


def test_schema_level_protocol_stub_is_deferred_until_canon_lands(repos):
    path = repos["protocol"] / cc.PROTOCOL_SCHEMA_DIR / "simple.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["x-status"] = "stub"
    doc["properties"]["mode"]["enum"] = ["totally", "different"]
    _write(path, doc)
    findings = _by_subject(cc.check_schemas(repos["runtime"], repos["protocol"], {}, set()))
    assert findings["wirelang/schemas/simple.json"].status == cc.STATUS_DEFERRED

    doc.pop("x-status")
    _write(path, doc)
    findings = _by_subject(cc.check_schemas(repos["runtime"], repos["protocol"], {}, set()))
    assert findings["wirelang/schemas/simple.json"].status == cc.STATUS_FAIL


def test_schema_level_active_allowlist_entry_turns_drift_into_allowed(repos):
    path = repos["protocol"] / cc.PROTOCOL_SCHEMA_DIR / "simple.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["properties"]["mode"]["enum"] = ["a", "b", "c"]
    _write(path, doc)
    entry = allow.AllowlistEntry(path="wirelang/schemas/simple.json", until=dt.date(2026, 12, 31), tracking=TRACKING)
    used: set[str] = set()
    findings = _by_subject(cc.check_schemas(repos["runtime"], repos["protocol"], {entry.path: entry}, used))
    assert findings["wirelang/schemas/simple.json"].status == cc.STATUS_ALLOWED
    assert TRACKING in findings["wirelang/schemas/simple.json"].detail
    assert used == {"wirelang/schemas/simple.json"}


def test_schema_level_missing_directories_fail(tmp_path: Path):
    findings = cc.check_schemas(tmp_path / "rt", tmp_path / "pr", {}, set())
    assert [f.status for f in findings] == [cc.STATUS_FAIL]


# ---------------------------------------------------------------------------
# Proof-schema selection
# ---------------------------------------------------------------------------


def test_proof_schema_selection_prefers_protocol_canon(repos):
    choice, findings = cc.select_proof_schema(repos["runtime"], repos["protocol"])
    assert choice is not None and choice.source == "protocol-canon" and choice.stub is None
    assert findings[0].status == cc.STATUS_OK


def test_proof_schema_selection_falls_back_on_stub(repos):
    path = repos["protocol"] / cc.PROTOCOL_SCHEMA_DIR / cc.PROOF_SCHEMA_FILE
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["x-status"] = "stub"
    _write(path, doc)
    choice, findings = cc.select_proof_schema(repos["runtime"], repos["protocol"])
    assert choice is not None and choice.source.startswith("runtime-draft") and choice.stub is not None
    assert findings[0].status == cc.STATUS_DEFERRED
    assert "FALLBACK" in findings[0].detail


def test_proof_schema_selection_without_any_schema_fails(repos):
    (repos["protocol"] / cc.PROTOCOL_SCHEMA_DIR / cc.PROOF_SCHEMA_FILE).unlink()
    (repos["runtime"] / cc.RUNTIME_SCHEMA_DIR / cc.PROOF_SCHEMA_FILE).unlink()
    choice, findings = cc.select_proof_schema(repos["runtime"], repos["protocol"])
    assert choice is None and findings[0].status == cc.STATUS_FAIL


# ---------------------------------------------------------------------------
# Levels that need wakir_verify
# ---------------------------------------------------------------------------


@pytest.fixture
def verify():
    pytest.importorskip("wakir_verify")
    return cc.import_verify(None)


def test_vector_level_reproduces_generated_vectors(repos, verify):
    choice, _ = cc.select_proof_schema(repos["runtime"], repos["protocol"])
    findings = _by_subject(cc.check_vectors(repos["protocol"], agg, verify, choice))
    assert {name: f.status for name, f in findings.items()} == {
        "vector-1.json": cc.STATUS_OK,
        "vector-2.json": cc.STATUS_OK,
        "vector-3.json": cc.STATUS_OK,
    }
    assert "tampered case rejected" in findings["vector-3.json"].detail


def test_vector_level_detects_root_and_sibling_drift(repos, verify):
    vec_path = repos["protocol"] / cc.PROTOCOL_VECTOR_DIR / "vector-2.json"
    vec = json.loads(vec_path.read_text(encoding="utf-8"))
    vec["merkle_root"] = "0" * 64
    _write(vec_path, vec)
    findings = _by_subject(cc.check_vectors(repos["protocol"], agg, verify, None))
    assert findings["vector-2.json"].status == cc.STATUS_FAIL
    assert "root" in findings["vector-2.json"].detail

    vec = json.loads(vec_path.read_text(encoding="utf-8"))
    vec = make_vector("vector-2", [_leaf(1), _leaf(2), _leaf(3)])
    vec["proofs"][2]["siblings"][0]["side"] = "L"
    _write(vec_path, vec)
    findings = _by_subject(cc.check_vectors(repos["protocol"], agg, verify, None))
    assert findings["vector-2.json"].status == cc.STATUS_FAIL
    assert "siblings" in findings["vector-2.json"].detail


def test_vector_level_tampered_leaf_that_verifies_is_red(repos, verify):
    vec_path = repos["protocol"] / cc.PROTOCOL_VECTOR_DIR / "vector-3.json"
    vec = json.loads(vec_path.read_text(encoding="utf-8"))
    vec["tampered"]["expected_verified"] = True
    _write(vec_path, vec)
    findings = _by_subject(cc.check_vectors(repos["protocol"], agg, verify, None))
    assert findings["vector-3.json"].status == cc.STATUS_FAIL
    assert "tampered" in findings["vector-3.json"].detail


def test_vector_level_without_proofs_is_deferred_not_red(repos, verify):
    vec_path = repos["protocol"] / cc.PROTOCOL_VECTOR_DIR / "vector-1.json"
    _write(vec_path, make_vector("vector-1", [_leaf(1)], with_proofs=False))
    findings = [f for f in cc.check_vectors(repos["protocol"], agg, verify, None) if f.subject == "vector-1.json"]
    assert {f.status for f in findings} == {cc.STATUS_DEFERRED, cc.STATUS_OK}


def test_vector_level_no_vectors_is_red(tmp_path: Path, verify):
    findings = cc.check_vectors(tmp_path, agg, verify, None)
    assert [f.status for f in findings] == [cc.STATUS_FAIL]


def test_full_run_passes_on_consistent_mock(repos, verify):
    report = _run(repos)
    assert not report.has_fail(), report.render_text()
    levels = {f.level for f in report.findings}
    assert {"setup", "schema", "vector", "manifest", "proof"} <= levels
    by_subject = _by_subject(report.findings, "manifest")
    assert by_subject["wakir_verify.manifest"].status == cc.STATUS_OK
    assert "constraint C1" in by_subject["wakir_verify.manifest"].detail
    assert by_subject["wat.verify.cli"].status == cc.STATUS_OK
    assert report.proof_schema_source == "protocol-canon"


def test_full_run_detects_manifest_root_tamper(repos, verify):
    path = repos["demo"] / HOUR / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["merkle_root"] = "1" * 64
    _write(path, doc)
    report = _run(repos)
    assert report.has_fail()
    assert any(f.level == "manifest" and f.status == cc.STATUS_FAIL for f in report.findings)


def test_full_run_detects_constraint_c1_violation(repos, verify):
    path = repos["demo"] / HOUR / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["envelope"] = "wakir-wat-manifest/v9"
    _write(path, doc)
    report = _run(repos)
    finding = _by_subject(report.findings, "manifest")["wakir_verify.manifest"]
    assert finding.status == cc.STATUS_FAIL and "C1" in finding.detail


def test_full_run_detects_manifest_version_drift(repos, verify):
    path = repos["demo"] / HOUR / "manifest.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["version"] = "wakir-wat-manifest/v2"
    _write(path, doc)
    report = _run(repos)
    version_findings = [f for f in report.findings if f.level == "manifest" and f.subject == "version"]
    assert version_findings and all(f.status == cc.STATUS_FAIL for f in version_findings)


def test_full_run_detects_proof_tamper_and_schema_violation(repos, verify):
    path = repos["demo"] / "proof.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["siblings"][0]["side"] = "L" if doc["siblings"][0]["side"] == "R" else "R"
    _write(path, doc)
    report = _run(repos)
    assert _by_subject(report.findings, "proof")["proof.json↔manifest"].status == cc.STATUS_FAIL

    doc["siblings"][0]["side"] = "X"
    _write(path, doc)
    report = _run(repos)
    assert _by_subject(report.findings, "proof")["proof.json"].status == cc.STATUS_FAIL


def test_full_run_missing_demo_artifacts_is_red(repos, verify):
    shutil.rmtree(repos["demo"])
    repos["demo"].mkdir()
    report = _run(repos)
    subjects = {f.subject for f in report.findings if f.status == cc.STATUS_FAIL}
    assert {"proof.json", "manifest.json"} <= subjects


def test_full_run_without_demo_workdir_is_red(repos, verify):
    report = _run(repos, demo_workdir=None)
    assert any(f.subject == "demo-workdir" and f.status == cc.STATUS_FAIL for f in report.findings)


def test_full_run_missing_protocol_checkout_is_setup_fail(repos, verify):
    report = _run(repos, protocol_root=repos["protocol"] / "nope")
    assert [f.level for f in report.findings] == ["setup"]
    assert report.has_fail()


def test_full_run_expired_and_unused_allowlist_entries(repos, verify):
    _write(
        repos["allowlist"],
        {
            "schema": allow.ALLOWLIST_SCHEMA,
            "entries": [
                {"path": "wirelang/schemas/simple.json", "until": "2026-09-01", "tracking": TRACKING},
                {"path": "wirelang/schemas/other.json", "until": "2026-12-31", "tracking": TRACKING},
            ],
        },
    )
    report = _run(repos)
    allow_findings = _by_subject(report.findings, "allowlist")
    assert allow_findings["wirelang/schemas/simple.json"].status == cc.STATUS_FAIL
    assert "expired" in allow_findings["wirelang/schemas/simple.json"].detail
    assert allow_findings["wirelang/schemas/other.json"].status == cc.STATUS_WARN


def test_full_run_invalid_allowlist_is_red(repos, verify):
    _write(repos["allowlist"], {"schema": allow.ALLOWLIST_SCHEMA, "entries": [{"path": "x.json", "tracking": TRACKING}]})
    report = _run(repos)
    assert any(f.level == "allowlist" and f.status == cc.STATUS_FAIL for f in report.findings)


def test_report_renderers(repos, verify):
    report = _run(repos)
    md = report.render_markdown()
    assert md.startswith("## cross-repo compatibility (protocol ↔ runtime ↔ verify)")
    assert "**Verdict:** PASS" in md
    assert "| schema | ok | `wirelang/schemas/simple.json` |" in md
    doc = report.to_json()
    assert doc["schema"] == "wakir-compat-report/v1"
    assert doc["verdict"] == cc.STATUS_OK
    assert doc["counts"][cc.STATUS_FAIL] == 0
    assert {"level", "status", "subject", "detail"} == set(doc["findings"][0])


def test_main_exit_codes_and_outputs(repos, verify, tmp_path: Path, capsys):
    summary = tmp_path / "out" / "summary.md"
    report_json = tmp_path / "out" / "report.json"
    rc = cc.main(
        [
            "--runtime", str(repos["runtime"]),
            "--protocol", str(repos["protocol"]),
            "--demo-workdir", str(repos["demo"]),
            "--allowlist", str(repos["allowlist"]),
            "--today", TODAY.isoformat(),
            "--summary-md", str(summary),
            "--report-json", str(report_json),
        ]
    )
    assert rc == 0
    assert "verdict=PASS" in capsys.readouterr().out
    assert summary.read_text(encoding="utf-8").startswith("## cross-repo compatibility")
    assert json.loads(report_json.read_text(encoding="utf-8"))["verdict"] == cc.STATUS_OK

    path = repos["protocol"] / cc.PROTOCOL_SCHEMA_DIR / "simple.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["properties"]["mode"]["enum"] = ["z"]
    _write(path, doc)
    rc = cc.main(
        [
            "--runtime", str(repos["runtime"]),
            "--protocol", str(repos["protocol"]),
            "--demo-workdir", str(repos["demo"]),
            "--allowlist", str(repos["allowlist"]),
            "--today", TODAY.isoformat(),
        ]
    )
    assert rc == 1
    assert "verdict=FAIL" in capsys.readouterr().out
