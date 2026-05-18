# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic tests for `scripts/audit/cross-repo-sync-audit.py`.

All fixtures synthesised in tmp_path. No network. No real
`wakir-protocol` clone. No git invocations. Pure stdlib + pytest.

Coverage targets:

1.  Allowlist parser — empty/inline-empty/list-with-mappings shapes.
2.  Allowlist parser — malformed-input sentinel paths.
3.  Mirror-pair audit — ok / DRIFT / drift-allowed / missing-*
    status taxonomy.
4.  Welle-substance audit — runtime triad completeness + module
    presence + optional protocol-doc mention.
5.  Welle-substance audit — protocol-doc absence is not drift
    (Cut-2 boundary).
6.  Welle-substance audit — runtime-incomplete is flagged.
7.  CLI exit-code matrix — audit-only vs enforce-mode.
8.  CLI missing protocol-root vs synthesized missing-protocol rows.
9.  Markdown report — recommendation block reacts to drift counts.
10. SHA-256 deterministic across runs.
11. Allowlist file `allow: []` is treated as empty waiver list.
12. Mirror-pair contract — every pair has all three substance
    classes represented at least once (no class regression).
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys
import textwrap


# ---------------------------------------------------------------------------
# Module loader — load the audit script as a module without installing it
# into the test package.
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_AUDIT_SCRIPT = _REPO_ROOT / "scripts" / "audit" / "cross-repo-sync-audit.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location(
        "cross_repo_sync_audit", _AUDIT_SCRIPT
    )
    assert spec is not None and spec.loader is not None, _AUDIT_SCRIPT
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


audit = _load_audit_module()


# ---------------------------------------------------------------------------
# Test fixtures — synthesised runtime + protocol roots.
# ---------------------------------------------------------------------------

def _make_runtime_root(tmp_path: pathlib.Path, *, welle_complete: bool = True
                       ) -> pathlib.Path:
    """
    Build a minimal runtime worktree shape — only the files the audit
    inspects need to exist.
    """
    runtime = tmp_path / "runtime"
    (runtime / "wirelang" / "schemas").mkdir(parents=True, exist_ok=True)
    (runtime / "wirelang" / "canonical").mkdir(parents=True, exist_ok=True)
    (runtime / "wirelang" / "identity").mkdir(parents=True, exist_ok=True)

    # All 10 mirror-pair runtime files.
    pair_files = [
        "wirelang/schemas/layer-0-transport.json",
        "wirelang/schemas/layer-1-wire.json",
        "wirelang/schemas/layer-2-semantic.json",
        "wirelang/schemas/layer-3-capability-token.json",
        "wirelang/schemas/aip-document.json",
        "wirelang/schemas/datalog-caveat.json",
        "wirelang/schemas/federation-trust-document.json",
        "wirelang/canonical/caveat_set.py",
        "wirelang/identity/aip_document.py",
        "wirelang/identity/dns_anchor.py",
    ]
    for rel in pair_files:
        f = runtime / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"runtime-fixture: {rel}\n", encoding="utf-8")

    # Welle triad: smoke + runbook + workflow + module dirs.
    if welle_complete:
        for w in audit.WELLE_INVENTORY:
            (runtime / w.smoke_script).parent.mkdir(parents=True, exist_ok=True)
            (runtime / w.smoke_script).write_text(
                f"# welle {w.welle} smoke", encoding="utf-8"
            )
            (runtime / w.runbook).parent.mkdir(parents=True, exist_ok=True)
            (runtime / w.runbook).write_text(
                f"# welle {w.welle} runbook", encoding="utf-8"
            )
            (runtime / w.validation_workflow).parent.mkdir(
                parents=True, exist_ok=True
            )
            (runtime / w.validation_workflow).write_text(
                f"# welle {w.welle} workflow", encoding="utf-8"
            )
            for mod in w.phase_3a_modules:
                (runtime / mod).mkdir(parents=True, exist_ok=True)
    return runtime


def _make_protocol_root(tmp_path: pathlib.Path, runtime_root: pathlib.Path,
                        *, mirror: bool = True,
                        welle_doc_mentions_all: bool = True
                        ) -> pathlib.Path:
    """
    Build a minimal protocol worktree mirroring (or not) runtime files.
    """
    protocol = tmp_path / "protocol"
    for pair in audit.MIRROR_PAIRS:
        dst = protocol / pair.protocol_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        if mirror:
            src = runtime_root / pair.runtime_path
            if src.is_file():
                dst.write_bytes(src.read_bytes())
            else:
                dst.write_text("placeholder", encoding="utf-8")
        else:
            dst.write_text(f"protocol-diverged: {pair.protocol_path}\n",
                           encoding="utf-8")

    # Optional welle-substance doc.
    doc = protocol / "docs" / "welle-substance.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    if welle_doc_mentions_all:
        body = "\n".join(f"- {w.protocol_doc_token}: substance"
                         for w in audit.WELLE_INVENTORY)
    else:
        body = "- only welle-1 and welle-2 mentioned"
    doc.write_text(body, encoding="utf-8")
    return protocol


# ---------------------------------------------------------------------------
# Test 1 — allowlist parser empty shapes.
# ---------------------------------------------------------------------------

def test_allowlist_parser_empty_shapes(tmp_path: pathlib.Path) -> None:
    cases = [
        ("", []),
        ("allow: []\n", []),
        ("allow:\n", []),
        ("# only comment\nallow: []\n", []),
    ]
    for text, expected in cases:
        result = audit.parse_allowlist(text)
        assert result == expected, (text, result)


# ---------------------------------------------------------------------------
# Test 2 — allowlist parser malformed inputs.
# ---------------------------------------------------------------------------

def test_allowlist_parser_malformed_inputs() -> None:
    malformed_cases = [
        # No `allow:` key at all.
        "wrong_key: []\n",
        # Inline empty followed by extra junk.
        "allow: []\nwrong_key: 1\n",
        # List item missing required keys.
        "allow:\n  - reason: foo\n",
        # Item with unknown key.
        "allow:\n  - runtime: a\n    protocol: b\n    unknown_key: c\n",
        # Garbled continuation line.
        "allow:\n  garbled\n",
    ]
    for text in malformed_cases:
        result = audit.parse_allowlist(text)
        assert result == "__MALFORMED__", (text, result)


# ---------------------------------------------------------------------------
# Test 3 — mirror-pair audit status taxonomy.
# ---------------------------------------------------------------------------

def test_mirror_pair_audit_all_ok_when_mirrored(tmp_path: pathlib.Path) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=True)

    results = audit.audit_mirror_pairs(runtime, protocol, allowlist=[])
    assert len(results) == len(audit.MIRROR_PAIRS)
    for r in results:
        assert r.status == "ok", r
        assert r.runtime_sha256 == r.protocol_sha256


def test_mirror_pair_audit_drift_when_diverged(tmp_path: pathlib.Path) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=False)

    results = audit.audit_mirror_pairs(runtime, protocol, allowlist=[])
    for r in results:
        assert r.status == "DRIFT", r


def test_mirror_pair_audit_allowlist_demotes_drift_to_allowed(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=False)
    # Allowlist only the first pair.
    first = audit.MIRROR_PAIRS[0]
    results = audit.audit_mirror_pairs(
        runtime, protocol,
        allowlist=[(first.runtime_path, first.protocol_path)],
    )
    assert results[0].status == "drift-allowed", results[0]
    for r in results[1:]:
        assert r.status == "DRIFT", r


def test_mirror_pair_audit_missing_on_either_side(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=True)

    # Delete one runtime file, one protocol file, and both for a third pair.
    (runtime / audit.MIRROR_PAIRS[0].runtime_path).unlink()
    (protocol / audit.MIRROR_PAIRS[1].protocol_path).unlink()
    (runtime / audit.MIRROR_PAIRS[2].runtime_path).unlink()
    (protocol / audit.MIRROR_PAIRS[2].protocol_path).unlink()

    results = audit.audit_mirror_pairs(runtime, protocol, allowlist=[])
    by_runtime = {r.runtime_path: r for r in results}
    assert by_runtime[audit.MIRROR_PAIRS[0].runtime_path].status \
        == "missing-runtime"
    assert by_runtime[audit.MIRROR_PAIRS[1].runtime_path].status \
        == "missing-protocol"
    assert by_runtime[audit.MIRROR_PAIRS[2].runtime_path].status \
        == "missing-both"


# ---------------------------------------------------------------------------
# Test 4 — welle audit triad completeness.
# ---------------------------------------------------------------------------

def test_welle_audit_runtime_complete_protocol_mentions_all(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, welle_doc_mentions_all=True)
    results = audit.audit_welle_inventory(
        runtime, protocol / "docs" / "welle-substance.md"
    )
    assert all(w.overall_status == "ok" for w in results), results
    assert all(w.smoke_present and w.runbook_present
               and w.validation_workflow_present for w in results)
    assert all(all(w.phase_3a_modules_present) for w in results)


# ---------------------------------------------------------------------------
# Test 5 — protocol doc absent => runtime-only (NOT drift).
# ---------------------------------------------------------------------------

def test_welle_audit_protocol_doc_absent_is_not_drift(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    # Pass a non-existent path; the audit should treat this as
    # Cut-2-compliant "runtime-only complete", NOT incomplete.
    results = audit.audit_welle_inventory(
        runtime, tmp_path / "no-such-protocol-doc.md"
    )
    for w in results:
        assert w.overall_status == "consistent-runtime-only", w
        assert w.protocol_doc_mentions_welle is None


# ---------------------------------------------------------------------------
# Test 6 — runtime triad incomplete is flagged.
# ---------------------------------------------------------------------------

def test_welle_audit_runtime_incomplete_flagged(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    # Remove the welle-3 smoke script.
    target = runtime / audit.WELLE_INVENTORY[2].smoke_script
    target.unlink()
    results = audit.audit_welle_inventory(runtime, None)
    by_welle = {w.welle: w for w in results}
    assert by_welle[3].overall_status == "incomplete-runtime"
    assert by_welle[3].smoke_present is False
    # Other welles should remain runtime-complete.
    for w in results:
        if w.welle != 3:
            assert w.overall_status == "consistent-runtime-only", w


def test_welle_audit_protocol_doc_partial_mention(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(
        tmp_path, runtime, welle_doc_mentions_all=False
    )
    results = audit.audit_welle_inventory(
        runtime, protocol / "docs" / "welle-substance.md"
    )
    by_welle = {w.welle: w for w in results}
    # Welles 1 and 2 are mentioned in the doc (substring "welle-1"
    # and "welle-2"); 3..7 are not.
    assert by_welle[1].overall_status == "ok"
    assert by_welle[2].overall_status == "ok"
    for n in (3, 4, 5, 6, 7):
        assert by_welle[n].overall_status == "protocol-doc-missing-mention", \
            by_welle[n]


# ---------------------------------------------------------------------------
# Test 7 — CLI exit-code matrix.
# ---------------------------------------------------------------------------

def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_AUDIT_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_clean_audit_exits_zero(tmp_path: pathlib.Path) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=True)
    cp = _run_cli([
        "--runtime-root", str(runtime),
        "--protocol-root", str(protocol),
        "--enforce",
    ])
    assert cp.returncode == 0, cp.stderr
    assert "mirror-pairs: ok=" in cp.stdout


def test_cli_drift_enforce_exits_one(tmp_path: pathlib.Path) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=False)
    cp = _run_cli([
        "--runtime-root", str(runtime),
        "--protocol-root", str(protocol),
        "--enforce",
    ])
    assert cp.returncode == 1, (cp.stdout, cp.stderr)


def test_cli_drift_audit_only_exits_zero(tmp_path: pathlib.Path) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=False)
    cp = _run_cli([
        "--runtime-root", str(runtime),
        "--protocol-root", str(protocol),
    ])
    assert cp.returncode == 0, (cp.stdout, cp.stderr)


def test_cli_invocation_error_exits_two(tmp_path: pathlib.Path) -> None:
    cp = _run_cli([
        "--runtime-root", str(tmp_path / "does-not-exist"),
    ])
    assert cp.returncode == 2, (cp.stdout, cp.stderr)


# ---------------------------------------------------------------------------
# Test 8 — missing protocol root yields synthesized rows + no enforce-fail.
# ---------------------------------------------------------------------------

def test_cli_missing_protocol_root_synthesizes_rows(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    cp = _run_cli([
        "--runtime-root", str(runtime),
        "--enforce",
    ])
    # Enforce mode without a protocol root: missing-protocol rows are
    # expected (synthesized) and MUST NOT cause a non-zero exit, per
    # the script's documented contract.
    assert cp.returncode == 0, (cp.stdout, cp.stderr)
    assert "missing=10" in cp.stdout


# ---------------------------------------------------------------------------
# Test 9 — markdown report recommendations react to inputs.
# ---------------------------------------------------------------------------

def test_markdown_report_clean_recommendations(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=True,
                                    welle_doc_mentions_all=True)
    report_path = tmp_path / "report.md"
    cp = _run_cli([
        "--runtime-root", str(runtime),
        "--protocol-root", str(protocol),
        "--report-path", str(report_path),
        "--date", "2026-05-18",
    ])
    assert cp.returncode == 0, cp.stderr
    body = report_path.read_text(encoding="utf-8")
    assert "No actions required" in body
    assert "**READY**" in body


def test_markdown_report_drift_recommendations(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=False,
                                    welle_doc_mentions_all=True)
    report_path = tmp_path / "report.md"
    cp = _run_cli([
        "--runtime-root", str(runtime),
        "--protocol-root", str(protocol),
        "--report-path", str(report_path),
        "--date", "2026-05-18",
    ])
    # Audit-only by default — exit 0 even with drift.
    assert cp.returncode == 0, cp.stderr
    body = report_path.read_text(encoding="utf-8")
    assert "un-allowlisted drift item" in body
    assert "**BLOCKED**" in body


def test_json_dump_contains_pair_and_welle_payload(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=True)
    json_path = tmp_path / "out.json"
    cp = _run_cli([
        "--runtime-root", str(runtime),
        "--protocol-root", str(protocol),
        "--json", str(json_path),
    ])
    assert cp.returncode == 0, cp.stderr
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "pairs" in payload and len(payload["pairs"]) == len(audit.MIRROR_PAIRS)
    assert "welle" in payload and len(payload["welle"]) == 7
    assert payload["enforce"] is False


# ---------------------------------------------------------------------------
# Test 10 — SHA-256 deterministic.
# ---------------------------------------------------------------------------

def test_sha256_deterministic_across_runs(tmp_path: pathlib.Path) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=True)
    r1 = audit.audit_mirror_pairs(runtime, protocol, allowlist=[])
    r2 = audit.audit_mirror_pairs(runtime, protocol, allowlist=[])
    assert [x._asdict() for x in r1] == [x._asdict() for x in r2]


# ---------------------------------------------------------------------------
# Test 11 — `allow: []` inline empty is an empty waiver list.
# ---------------------------------------------------------------------------

def test_allowlist_inline_empty_is_no_waiver(tmp_path: pathlib.Path) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=False)
    aw = runtime / ".cross-repo-drift-allowlist.yaml"
    aw.write_text("allow: []\n", encoding="utf-8")
    cp = _run_cli([
        "--runtime-root", str(runtime),
        "--protocol-root", str(protocol),
        "--enforce",
    ])
    assert cp.returncode == 1, (cp.stdout, cp.stderr)


# ---------------------------------------------------------------------------
# Test 12 — mirror-pair contract — all four runtime-side substance
# classes (layer-0..3, aip, capability) present at least once.
# ---------------------------------------------------------------------------

def test_mirror_pair_contract_covers_all_substance_classes() -> None:
    classes = {p.substance_class for p in audit.MIRROR_PAIRS}
    # Layer 0-3 schemas:
    for n in range(4):
        assert f"layer-{n}-schema" in classes, classes
    assert "aip" in classes
    assert "capability" in classes


# ---------------------------------------------------------------------------
# Test 13 — welle inventory contract — exactly 7 welles, numbered 1..7.
# ---------------------------------------------------------------------------

def test_welle_inventory_contract_is_one_to_seven() -> None:
    welles = [w.welle for w in audit.WELLE_INVENTORY]
    assert welles == [1, 2, 3, 4, 5, 6, 7]
    for w in audit.WELLE_INVENTORY:
        assert w.smoke_script.startswith("scripts/")
        assert w.runbook.endswith(".md")
        assert w.validation_workflow.startswith(".github/workflows/")
        assert w.phase_3a_modules
        assert w.protocol_doc_token == f"welle-{w.welle}"


# ---------------------------------------------------------------------------
# Test 14 — malformed allowlist on disk triggers enforce-mode fail.
# ---------------------------------------------------------------------------

def test_malformed_allowlist_blocks_enforce_mode(
    tmp_path: pathlib.Path,
) -> None:
    runtime = _make_runtime_root(tmp_path)
    protocol = _make_protocol_root(tmp_path, runtime, mirror=True)
    aw = runtime / ".cross-repo-drift-allowlist.yaml"
    aw.write_text(textwrap.dedent("""\
        allow:
          - wrong_key: foo
        """), encoding="utf-8")
    cp = _run_cli([
        "--runtime-root", str(runtime),
        "--protocol-root", str(protocol),
        "--enforce",
    ])
    # Mirror is clean — but malformed allowlist must still red the run.
    assert cp.returncode == 1, (cp.stdout, cp.stderr)
    assert "allowlist malformed" in cp.stderr.lower()
