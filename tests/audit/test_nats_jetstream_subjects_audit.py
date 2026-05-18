# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for `scripts/audit/nats-jetstream-subjects-audit.py`.

All fixtures synthesised in ``tmp_path``. No network. No real
wakir-runtime scan. Pure stdlib + pytest.

Coverage targets (Tag-43, Selin):

1.  ``classify_call`` returns the expected sigil for each
    publish/subscribe surface and ``None`` for comment lines.
2.  ``classify_subject_template`` distinguishes ``ok`` /
    ``regex-drift`` / ``template-drift`` / ``namespace-id`` per
    the canonical ``wakir.<env>.<domain>.…`` rule.
3.  ``scan_calls`` skips docstring-embedded sigils.
4.  ``scan_subjects`` reports the literal-line cleanly and
    de-duplicates same-line repeats.
5.  ``audit_repo`` over a clean fixture reports zero drift.
6.  ``audit_repo`` over a drifted fixture surfaces the regex-
    drift literal and the namespace-id row.
7.  ``cross_validate_modes`` flags an ``nc.publish``-only module
    that references the publish-mode discriminator as
    ``adapter-incomplete``.
8.  ``adapter_config_audit`` flags a subscriber that imports the
    contract but does not call ``require_compatible`` as
    ``preflight-gate-missing``.
9.  ``adapter_config_audit`` treats a publisher-only contract
    importer without ``require_compatible`` as
    ``publisher-no-gate`` (informational, NOT drift).
10. ``render_report`` is deterministic — two runs with the same
    fixture and the same ``generated_at`` produce identical
    SHA-256.
11. CLI ``--enforce`` exits 0 on a clean fixture and non-zero on
    a drifted fixture.
12. CLI ``--report`` writes the report file and the file content
    matches the in-process render.
13. ``audit_repo`` excludes ``tests/`` and ``.worktree-*`` paths
    even if they contain matching literals.
14. ``SCHEMA_SUBJECT_REGEX`` mirrors the runtime substrate (this
    asserts that the audit's mirror regex matches the canonical
    template-build outputs ``wakir.dev.agent.task.assigned``).
"""

from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import subprocess
import sys
import textwrap


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_AUDIT_SCRIPT = _REPO_ROOT / "scripts" / "audit" / "nats-jetstream-subjects-audit.py"


def _load_audit_module():
    module_name = "nats_jetstream_subjects_audit"
    spec = importlib.util.spec_from_file_location(
        module_name, _AUDIT_SCRIPT
    )
    assert spec is not None and spec.loader is not None, _AUDIT_SCRIPT
    mod = importlib.util.module_from_spec(spec)
    # Python 3.14+ dataclasses requires the module to be in sys.modules
    # before exec_module so frozen dataclass class creation can look
    # up the owning module's __dict__.
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


audit = _load_audit_module()


# ---------------------------------------------------------------------------
# Fixture synthesis helpers
# ---------------------------------------------------------------------------


def _make_clean_repo(root: pathlib.Path) -> pathlib.Path:
    """Build a fixture repo with no drift."""

    (root / "wirelang" / "cli").mkdir(parents=True)
    (root / "wirelang" / "persona_engine").mkdir(parents=True)
    (root / "scripts" / "audit").mkdir(parents=True)

    # Publisher with both nc.publish and js.publish + publish-mode
    # discriminator — Adapter-B complete.
    (root / "wirelang" / "cli" / "publisher.py").write_text(
        textwrap.dedent(
            '''
            """Sample publisher."""
            from wirelang.persona_engine.publish_mode_contract import (
                PUBLISH_MODE_JETSTREAM,
                resolve_publish_mode,
            )

            async def main(nc, js):
                mode = resolve_publish_mode()
                if mode == PUBLISH_MODE_JETSTREAM:
                    await js.publish("wakir.dev.agent.task.assigned", b"x")
                else:
                    await nc.publish("wakir.dev.agent.task.assigned", b"x")
            '''
        ).lstrip(),
        encoding="utf-8",
    )

    # Subscriber with require_compatible.
    (root / "wirelang" / "persona_engine" / "subscriber.py").write_text(
        textwrap.dedent(
            '''
            """Sample subscriber."""
            from wirelang.persona_engine.publish_mode_contract import (
                require_compatible,
            )

            async def main(nc):
                require_compatible("core", "core")
                sub = await nc.subscribe("wakir.dev.agent.task.assigned")
                return sub
            '''
        ).lstrip(),
        encoding="utf-8",
    )

    return root


def _make_drifted_repo(root: pathlib.Path) -> pathlib.Path:
    """Build a fixture repo with one regex-drift literal."""

    _make_clean_repo(root)
    # Add a module with a malformed subject literal — wakir.<env>.
    # prefix but a bad event token.
    (root / "wirelang" / "cli" / "drift.py").write_text(
        textwrap.dedent(
            '''
            """Drift fixture."""
            async def emit(nc):
                # Bad: the third token "Agent" is uppercase.
                await nc.publish("wakir.dev.Agent.task.assigned", b"x")
            '''
        ).lstrip(),
        encoding="utf-8",
    )
    return root


# ---------------------------------------------------------------------------
# Test 1 — classify_call
# ---------------------------------------------------------------------------


def test_classify_call_publish_core() -> None:
    assert audit.classify_call("    await nc.publish(subject, payload)") == "publish-core"


def test_classify_call_publish_jetstream() -> None:
    assert audit.classify_call("    await js.publish(subject, payload)") == "publish-jetstream"


def test_classify_call_subscribe_core() -> None:
    assert audit.classify_call("sub = await nc.subscribe(s, cb=h)") == "subscribe-core"


def test_classify_call_subscribe_jetstream() -> None:
    assert audit.classify_call("await js.subscribe(s)") == "subscribe-jetstream"


def test_classify_call_polyglot_sigil() -> None:
    assert audit.classify_call("var sub = nats.SubscribeAsync(s);") == "subscribe-polyglot"


def test_classify_call_skips_comment() -> None:
    assert audit.classify_call("# await js.publish(subject, payload)") is None
    assert audit.classify_call("// await js.publish(subject, payload)") is None


def test_classify_call_returns_none_on_unrelated_line() -> None:
    assert audit.classify_call("    print('hello world')") is None


# ---------------------------------------------------------------------------
# Test 2 — classify_subject_template
# ---------------------------------------------------------------------------


def test_classify_subject_concrete_ok() -> None:
    verdict, _ = audit.classify_subject_template(
        "wakir.dev.agent.task.assigned.tomas"
    )
    assert verdict == "ok"


def test_classify_subject_regex_drift() -> None:
    verdict, detail = audit.classify_subject_template(
        "wakir.dev.Agent.task.assigned"
    )
    assert verdict == "regex-drift"
    assert "SCHEMA_SUBJECT_REGEX" in detail


def test_classify_subject_template_ok() -> None:
    verdict, _ = audit.classify_subject_template(
        "wakir.{env}.agent.task.assigned.{persona_slug}"
    )
    assert verdict == "ok"


def test_classify_subject_template_unknown_placeholder() -> None:
    verdict, detail = audit.classify_subject_template(
        "wakir.{env}.agent.task.assigned.{tomato}"
    )
    assert verdict == "template-drift"
    assert "tomato" in detail


def test_classify_subject_namespace_id_concrete() -> None:
    verdict, _ = audit.classify_subject_template("wakir.persona_engine.meter")
    assert verdict == "namespace-id"


def test_classify_subject_namespace_id_template() -> None:
    verdict, _ = audit.classify_subject_template("wakir.{persona}.meter")
    assert verdict == "namespace-id"


# ---------------------------------------------------------------------------
# Test 3 — scan_calls skips docstring sigils
# ---------------------------------------------------------------------------


def test_scan_calls_skips_docstring_sigil(tmp_path: pathlib.Path) -> None:
    src = textwrap.dedent(
        '''
        """Module docstring with a literal js.publish(...) sigil
        that must NOT be classified."""
        async def real(nc):
            await nc.publish("wakir.dev.agent.task.assigned", b"x")
        '''
    ).lstrip()
    path = tmp_path / "m.py"
    path.write_text(src, encoding="utf-8")
    rows = audit.scan_calls(path, src)
    kinds = {r.kind for r in rows}
    # Only the real nc.publish should appear.
    assert kinds == {"publish-core"}, kinds


# ---------------------------------------------------------------------------
# Test 4 — scan_subjects line + dedup
# ---------------------------------------------------------------------------


def test_scan_subjects_reports_line_and_dedup(tmp_path: pathlib.Path) -> None:
    src = (
        '\n'
        '# header\n'
        'a = "wakir.dev.agent.task.assigned"\n'
        'b = ("wakir.dev.agent.task.assigned", "wakir.dev.agent.task.assigned")\n'
    )
    path = tmp_path / "m.py"
    path.write_text(src, encoding="utf-8")
    rows = audit.scan_subjects(path, src)
    # Line 3 (a=…) and line 4 (b=…). Same-line repeat on line 4
    # must dedup to a single row.
    by_line = {r.line for r in rows}
    assert by_line == {3, 4}
    # Both rows are verdict ok.
    assert {r.verdict for r in rows} == {"ok"}


# ---------------------------------------------------------------------------
# Test 5 — clean fixture → 0 drift
# ---------------------------------------------------------------------------


def test_audit_repo_clean_zero_drift(tmp_path: pathlib.Path) -> None:
    _make_clean_repo(tmp_path)
    result = audit.audit_repo(tmp_path)
    assert result.drift_count == 0, result


# ---------------------------------------------------------------------------
# Test 6 — drifted fixture → regex-drift row surfaces
# ---------------------------------------------------------------------------


def test_audit_repo_drifted_surfaces_regex_drift(tmp_path: pathlib.Path) -> None:
    _make_drifted_repo(tmp_path)
    result = audit.audit_repo(tmp_path)
    drift_rows = [
        s for s in result.subjects
        if s.verdict == "regex-drift"
    ]
    assert len(drift_rows) == 1, [s.literal for s in result.subjects]
    assert drift_rows[0].literal == "wakir.dev.Agent.task.assigned"


# ---------------------------------------------------------------------------
# Test 7 — adapter-incomplete (mode marker + nc.publish only)
# ---------------------------------------------------------------------------


def test_cross_validate_modes_flags_adapter_incomplete(
    tmp_path: pathlib.Path,
) -> None:
    src = textwrap.dedent(
        '''
        """Bad publisher: references mode but only calls nc.publish."""
        from wirelang.persona_engine.publish_mode_contract import (
            PUBLISH_MODE_JETSTREAM,
        )

        async def main(nc):
            mode = PUBLISH_MODE_JETSTREAM
            await nc.publish("wakir.dev.agent.task.assigned", b"x")
        '''
    ).lstrip()
    path = tmp_path / "bad_publisher.py"
    path.write_text(src, encoding="utf-8")
    calls = audit.scan_calls(path, src)
    row = audit.cross_validate_modes(path, src, calls)
    assert row is not None
    assert row.verdict == "adapter-incomplete", row


# ---------------------------------------------------------------------------
# Test 8 — preflight-gate-missing on subscriber w/o require_compatible
# ---------------------------------------------------------------------------


def test_adapter_audit_flags_preflight_gate_missing(
    tmp_path: pathlib.Path,
) -> None:
    src = textwrap.dedent(
        '''
        """Bad subscriber: imports contract but no require_compatible."""
        from wirelang.persona_engine.publish_mode_contract import (
            VERDICT_COMPATIBLE,
        )

        async def main(nc):
            sub = await nc.subscribe("wakir.dev.agent.task.assigned")
            return sub, VERDICT_COMPATIBLE
        '''
    ).lstrip()
    path = tmp_path / "bad_subscriber.py"
    path.write_text(src, encoding="utf-8")
    calls = audit.scan_calls(path, src)
    row = audit.adapter_config_audit(path, src, calls)
    assert row is not None
    assert row.verdict == "preflight-gate-missing", row


# ---------------------------------------------------------------------------
# Test 9 — publisher-no-gate is informational, not drift
# ---------------------------------------------------------------------------


def test_adapter_audit_publisher_no_gate_is_informational(
    tmp_path: pathlib.Path,
) -> None:
    src = textwrap.dedent(
        '''
        """Publisher without require_compatible — informational."""
        from wirelang.persona_engine.publish_mode_contract import (
            PUBLISH_MODE_JETSTREAM,
            resolve_publish_mode,
        )

        async def main(nc, js):
            mode = resolve_publish_mode()
            if mode == PUBLISH_MODE_JETSTREAM:
                await js.publish("wakir.dev.agent.task.assigned", b"x")
            else:
                await nc.publish("wakir.dev.agent.task.assigned", b"x")
        '''
    ).lstrip()
    path = tmp_path / "publisher.py"
    path.write_text(src, encoding="utf-8")
    calls = audit.scan_calls(path, src)
    row = audit.adapter_config_audit(path, src, calls)
    assert row is not None
    assert row.verdict == "publisher-no-gate", row

    # And the in-aggregate audit must count this as zero drift.
    (tmp_path / "wirelang" / "cli").mkdir(parents=True)
    (tmp_path / "wirelang" / "cli" / "publisher.py").write_text(src, encoding="utf-8")
    path.unlink()
    result = audit.audit_repo(tmp_path)
    publisher_rows = [
        a for a in result.adapter_checks if a.verdict == "publisher-no-gate"
    ]
    assert publisher_rows, result.adapter_checks
    assert result.drift_count == 0


# ---------------------------------------------------------------------------
# Test 10 — render_report deterministic SHA-256
# ---------------------------------------------------------------------------


def test_render_report_is_deterministic(tmp_path: pathlib.Path) -> None:
    _make_clean_repo(tmp_path)
    result1 = audit.audit_repo(tmp_path)
    result2 = audit.audit_repo(tmp_path)
    md1 = audit.render_report(result1, generated_at="2026-05-18T00:00:00Z")
    md2 = audit.render_report(result2, generated_at="2026-05-18T00:00:00Z")
    assert hashlib.sha256(md1.encode("utf-8")).hexdigest() == \
        hashlib.sha256(md2.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Test 11 — CLI exit codes
# ---------------------------------------------------------------------------


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_AUDIT_SCRIPT), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_enforce_clean_fixture_exit_zero(tmp_path: pathlib.Path) -> None:
    _make_clean_repo(tmp_path)
    result = _run_cli(
        "--repo-root", str(tmp_path),
        "--enforce",
        "--utc-date", "2026-05-18T00:00:00Z",
    )
    assert result.returncode == 0, result.stderr


def test_cli_enforce_drifted_fixture_exit_nonzero(
    tmp_path: pathlib.Path,
) -> None:
    _make_drifted_repo(tmp_path)
    result = _run_cli(
        "--repo-root", str(tmp_path),
        "--enforce",
        "--utc-date", "2026-05-18T00:00:00Z",
    )
    assert result.returncode != 0, result.stdout
    assert "ENFORCE-MODE FAIL" in result.stderr


# ---------------------------------------------------------------------------
# Test 12 — CLI --report writes the file
# ---------------------------------------------------------------------------


def test_cli_report_writes_file(tmp_path: pathlib.Path) -> None:
    _make_clean_repo(tmp_path)
    out_path = tmp_path / "out" / "audit.md"
    result = _run_cli(
        "--repo-root", str(tmp_path),
        "--report", str(out_path),
        "--utc-date", "2026-05-18T00:00:00Z",
    )
    assert result.returncode == 0, result.stderr
    assert out_path.is_file()
    written = out_path.read_text(encoding="utf-8")
    # Cross-check against in-process render with same generated_at.
    result_in_proc = audit.audit_repo(tmp_path)
    md_in_proc = audit.render_report(
        result_in_proc, generated_at="2026-05-18T00:00:00Z"
    )
    assert written == md_in_proc


# ---------------------------------------------------------------------------
# Test 13 — excluded paths are skipped
# ---------------------------------------------------------------------------


def test_audit_excludes_tests_and_worktree_paths(
    tmp_path: pathlib.Path,
) -> None:
    _make_clean_repo(tmp_path)
    # Add a tests/ file with a drift literal that should be ignored.
    (tmp_path / "tests" / "audit").mkdir(parents=True)
    (tmp_path / "tests" / "audit" / "test_should_be_skipped.py").write_text(
        '\n# wakir.dev.Agent.task.assigned should be ignored\n'
        'X = "wakir.dev.Agent.task.assigned"\n',
        encoding="utf-8",
    )
    # And a .worktree-* sub-tree.
    (tmp_path / ".worktree-foo" / "src").mkdir(parents=True)
    (tmp_path / ".worktree-foo" / "src" / "bad.py").write_text(
        'X = "wakir.dev.Agent.task.assigned"\n',
        encoding="utf-8",
    )

    result = audit.audit_repo(tmp_path)
    # Zero drift even with the malformed literals under tests/ and
    # .worktree-*/.
    assert result.drift_count == 0


# ---------------------------------------------------------------------------
# Test 14 — schema regex parity with runtime substrate
# ---------------------------------------------------------------------------


def test_schema_regex_matches_canonical_subject() -> None:
    """The audit's mirror regex must accept every canonical
    template-build output. This guards against the audit silently
    drifting from the runtime ``subject_mapping`` regex."""

    canonical_examples = (
        "wakir.dev.agent.task.assigned",
        "wakir.prod.wat.audit.anchor.created",
        "wakir.staging.aip.aip.document.published",
        "wakir.prod.aip.aip.document.published.reza",
        "wakir.prod.cap.cap.token.issued.mira",
    )
    for s in canonical_examples:
        assert audit.SCHEMA_SUBJECT_REGEX.match(s), s
