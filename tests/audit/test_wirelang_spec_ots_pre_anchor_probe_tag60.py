# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-60 hermetic invariants for the Wirelang-Spec OTS pre-anchor probe.

This suite covers the Tag-60 emit helper at
``tooling/ots/emit_wirelang_spec_ots_marker.py`` and its companion
stub registry, workflow, and runbook. All tests are stdlib-only; no
network I/O, no subprocess to ``ots`` CLI, no podman socket. The
test-suite is a mirror-twin of Tomás's Tag-59 manifest-hash probe
suite (``tests/ci/test_ots_pre_anchor_activation_probe_tag59.py``).

Test count: 18 (>= 12 per Tag-60 brief).
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import io
import json
import sys
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER_PATH = REPO_ROOT / "tooling" / "ots" / "emit_wirelang_spec_ots_marker.py"
STUB_PATH = REPO_ROOT / "tooling" / "ots" / "wirelang-spec-ots-anchor-stub.json"
WORKFLOW_PATH = (
    REPO_ROOT / ".github" / "workflows" / "wirelang-spec-ots-pre-anchor-probe.yml"
)
RUNBOOK_PATH = (
    REPO_ROOT / "docs" / "operations" / "wirelang-spec-ots-anchor-wiring.md"
)


def _load_helper_module():
    spec = importlib.util.spec_from_file_location(
        "emit_wirelang_spec_ots_marker", HELPER_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load helper at {HELPER_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


HELPER = _load_helper_module()


FIXED_NOW = _dt.datetime(2026, 5, 19, 5, 0, 0, tzinfo=_dt.timezone.utc)


def _write_minimal_spec(tmpdir: Path, version: str = "0.4.3") -> Path:
    """Create a small Wirelang-Spec stand-in with a valid frontmatter."""
    spec = tmpdir / f"wirelang-spec-v{version.replace('.', '-')}.md"
    spec.write_text(
        textwrap.dedent(
            f"""\
            <!--
            SPDX-License-Identifier: CC-BY-4.0
            -->

            ---
            spec: wirelang
            version: {version}
            status: pre-cutover-freeze
            freeze-marker: kw-24-cutover-gate
            ---

            # Wirelang Specification v{version}

            Test body.

            — Reza
            """
        ),
        encoding="utf-8",
    )
    return spec


class TestT01HelperLoadable(unittest.TestCase):
    """T01: helper module imports cleanly and exposes the expected API."""

    def test_helper_loaded(self) -> None:
        self.assertTrue(hasattr(HELPER, "compute_sha256"))
        self.assertTrue(hasattr(HELPER, "build_marker"))
        self.assertTrue(hasattr(HELPER, "build_probe_verdict"))
        self.assertTrue(hasattr(HELPER, "run_pre_activation_probe"))
        self.assertTrue(hasattr(HELPER, "main"))


class TestT02MarkerRequiredKeys(unittest.TestCase):
    """T02: marker required-key frozenset matches the spec in the docstring."""

    def test_required_keys(self) -> None:
        expected = {
            "schema_version",
            "kind",
            "mode",
            "spec_path",
            "spec_version",
            "spec_sha256",
            "spec_size_bytes",
            "wat_spool_envelope",
            "emitted_at_utc",
            "anchors",
            "operator_hand_next_step",
        }
        self.assertEqual(set(HELPER.MARKER_REQUIRED_KEYS), expected)


class TestT03ProbeVerdictRequiredKeys(unittest.TestCase):
    """T03: probe-verdict required-key frozenset matches schema-v1."""

    def test_required_keys(self) -> None:
        expected = {
            "schema_version",
            "kind",
            "mode",
            "verdict",
            "stages",
            "spec_sha256",
            "spec_size_bytes",
            "probed_at_utc",
            "ar_authorisation_required",
            "anchors",
        }
        self.assertEqual(set(HELPER.PROBE_VERDICT_REQUIRED_KEYS), expected)


class TestT04ProbeStageKeysExact(unittest.TestCase):
    """T04: probe-stage tuple matches the four documented stages, in order."""

    def test_stage_keys(self) -> None:
        self.assertEqual(
            HELPER.PROBE_STAGE_KEYS,
            (
                "input_validation",
                "hash_computation",
                "payload_shape",
                "sandbox_boundary",
            ),
        )


class TestT05ComputeSha256StreamingByteStable(unittest.TestCase):
    """T05: SHA-256 is byte-stable across small + chunk-boundary inputs."""

    def test_streaming(self) -> None:
        import tempfile, hashlib  # noqa: E401

        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "spec.md"
            payload = (b"x" * 65537) + b"\n"  # crosses 64 KiB boundary.
            p.write_bytes(payload)
            digest, size = HELPER.compute_sha256(p)
            self.assertEqual(size, len(payload))
            self.assertEqual(digest, hashlib.sha256(payload).hexdigest())


class TestT06BuildMarkerShape(unittest.TestCase):
    """T06: build_marker emits all required keys, no extras, correct kind."""

    def test_marker_shape(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = _write_minimal_spec(tmp)
            sha256, size = HELPER.compute_sha256(spec)
            marker = HELPER.build_marker(
                spec_path=spec,
                spec_sha256=sha256,
                spec_size_bytes=size,
                actor="tester",
                now_utc=FIXED_NOW,
                repo_root=tmp,
            )
            self.assertEqual(
                set(marker.keys()), set(HELPER.MARKER_REQUIRED_KEYS)
            )
            self.assertEqual(marker["kind"], "wirelang-spec-ots-anchor-marker")
            self.assertEqual(marker["schema_version"], 1)
            self.assertEqual(marker["mode"], "audit-only")
            self.assertEqual(marker["spec_sha256"], sha256)
            self.assertEqual(marker["spec_size_bytes"], size)
            self.assertEqual(marker["spec_version"], "0.4.3")
            envelope = marker["wat_spool_envelope"]
            self.assertEqual(envelope["schema_version"], 1)
            self.assertEqual(envelope["kind"], "wirelang-spec-ots-anchor-request")
            self.assertEqual(envelope["anchor_target"], "opentimestamps-calendar")
            self.assertEqual(envelope["spec_sha256"], sha256)


class TestT07ProbeReadyOnHappyPath(unittest.TestCase):
    """T07: probe verdict is PROBE-READY on a clean fixture spec."""

    def test_probe_ready(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = _write_minimal_spec(tmp)
            verdict = HELPER.run_pre_activation_probe(
                spec_path=spec,
                actor="tester",
                now_utc=FIXED_NOW,
                repo_root=tmp,  # fixture lives outside the real repo
            )
            self.assertEqual(verdict["verdict"], "PROBE-READY")
            for k in HELPER.PROBE_STAGE_KEYS:
                self.assertTrue(
                    verdict["stages"][k].startswith("OK"),
                    f"stage {k} not OK: {verdict['stages'][k]!r}",
                )
            self.assertIs(verdict["ar_authorisation_required"], True)


class TestT08ProbeDefectOnMissingSpec(unittest.TestCase):
    """T08: probe verdict is PROBE-DEFECT when the spec file is absent."""

    def test_missing_spec(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = tmp / "does-not-exist.md"
            verdict = HELPER.run_pre_activation_probe(
                spec_path=spec,
                actor="tester",
                now_utc=FIXED_NOW,
                repo_root=tmp,
            )
            self.assertEqual(verdict["verdict"], "PROBE-DEFECT")
            self.assertTrue(
                verdict["stages"]["input_validation"].startswith("FAIL")
            )
            self.assertEqual(verdict["spec_sha256"], "")
            self.assertEqual(verdict["spec_size_bytes"], 0)


class TestT09ProbeVerdictEnvelopeKeys(unittest.TestCase):
    """T09: probe verdict envelope shape matches the schema-v1 required-key set."""

    def test_verdict_keys(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = _write_minimal_spec(tmp)
            verdict = HELPER.run_pre_activation_probe(
                spec_path=spec,
                actor="tester",
                now_utc=FIXED_NOW,
                repo_root=tmp,
            )
            self.assertEqual(
                set(verdict.keys()),
                set(HELPER.PROBE_VERDICT_REQUIRED_KEYS),
            )
            self.assertEqual(
                verdict["kind"], "ots-pre-activation-probe-verdict"
            )
            self.assertEqual(verdict["mode"], "pre-activation-probe")
            self.assertIn(verdict["verdict"], ("PROBE-READY", "PROBE-DEFECT"))


class TestT10MainCLIPreActivationProbe(unittest.TestCase):
    """T10: ``main`` writes a probe verdict JSON when --mode probe is used."""

    def test_main_probe(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = _write_minimal_spec(tmp)
            verdict_path = tmp / "out" / "verdict.json"
            rc = HELPER.main(
                [
                    "--mode",
                    "pre-activation-probe",
                    "--spec",
                    str(spec),
                    "--probe-verdict-out",
                    str(verdict_path),
                    "--actor",
                    "tester",
                    "--now",
                    FIXED_NOW.isoformat(),
                    "--repo-root",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0)
            self.assertTrue(verdict_path.is_file())
            data = json.loads(verdict_path.read_text(encoding="utf-8"))
            self.assertEqual(data["verdict"], "PROBE-READY")
            self.assertEqual(
                data["kind"], "ots-pre-activation-probe-verdict"
            )


class TestT11MainCLIAuditOnly(unittest.TestCase):
    """T11: ``main`` writes a marker JSON when --mode audit-only is used."""

    def test_main_audit_only(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = _write_minimal_spec(tmp)
            marker_path = tmp / "out" / "marker.json"
            rc = HELPER.main(
                [
                    "--mode",
                    "audit-only",
                    "--spec",
                    str(spec),
                    "--marker-out",
                    str(marker_path),
                    "--actor",
                    "tester",
                    "--now",
                    FIXED_NOW.isoformat(),
                    "--repo-root",
                    str(tmp),
                ]
            )
            self.assertEqual(rc, 0)
            data = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(data["kind"], "wirelang-spec-ots-anchor-marker")
            self.assertEqual(data["mode"], "audit-only")


class TestT12MainCLIUsageErrorsExit2(unittest.TestCase):
    """T12: ``main`` exits 2 when required output flag is missing."""

    def test_missing_marker_out(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = _write_minimal_spec(tmp)
            # Capture stderr.
            captured = io.StringIO()
            real_stderr = sys.stderr
            sys.stderr = captured
            try:
                rc = HELPER.main(
                    [
                        "--mode",
                        "audit-only",
                        "--spec",
                        str(spec),
                    ]
                )
            finally:
                sys.stderr = real_stderr
            self.assertEqual(rc, 2)
            self.assertIn("--marker-out", captured.getvalue())

    def test_missing_probe_verdict_out(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            spec = _write_minimal_spec(tmp)
            captured = io.StringIO()
            real_stderr = sys.stderr
            sys.stderr = captured
            try:
                rc = HELPER.main(
                    [
                        "--mode",
                        "pre-activation-probe",
                        "--spec",
                        str(spec),
                    ]
                )
            finally:
                sys.stderr = real_stderr
            self.assertEqual(rc, 2)
            self.assertIn("--probe-verdict-out", captured.getvalue())


class TestT13StubJSONValid(unittest.TestCase):
    """T13: anchor-stub JSON is valid, schema_version=1, lists v0.4.3."""

    def test_stub_valid(self) -> None:
        data = json.loads(STUB_PATH.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["kind"], "wirelang-spec-ots-anchor-stub")
        self.assertEqual(data["mode"], "audit-only")
        paths = {s["path"] for s in data["wired_specs"]}
        self.assertIn(
            "wirelang/specs/wirelang-spec-v0-4-3.md", paths
        )
        sb = data["sandbox_boundary"]
        self.assertTrue(sb["no_network_io"])
        self.assertTrue(sb["no_ots_cli_subprocess"])
        self.assertTrue(sb["no_calendar_call"])
        cross = data["cross_anchor_with_tomas_tag_59"]
        self.assertEqual(
            cross["manifest_hash_stub"],
            "tooling/ots/manifest-hash-ots-anchor-stub.json",
        )


class TestT14StubRegistryEnforcement(unittest.TestCase):
    """T14: probe FAILs when the in-repo spec is NOT listed in the stub."""

    def test_unlisted_spec_in_repo(self) -> None:
        # Synthesize a stub at a tmp repo_root that whitelists only a
        # known path, then probe a different path inside that repo_root.
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            (tmp / "tooling" / "ots").mkdir(parents=True)
            (tmp / "tooling" / "ots" / "wirelang-spec-ots-anchor-stub.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "kind": "wirelang-spec-ots-anchor-stub",
                        "wired_specs": [
                            {
                                "name": "allowed",
                                "path": "wirelang/specs/allowed.md",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            # Synthesize an unlisted spec inside the repo_root.
            (tmp / "wirelang" / "specs").mkdir(parents=True)
            unlisted = tmp / "wirelang" / "specs" / "unlisted.md"
            unlisted.write_text("# unlisted\n", encoding="utf-8")
            verdict = HELPER.run_pre_activation_probe(
                spec_path=unlisted,
                actor="tester",
                now_utc=FIXED_NOW,
                repo_root=tmp,
            )
            self.assertEqual(verdict["verdict"], "PROBE-DEFECT")
            self.assertIn(
                "not listed",
                verdict["stages"]["input_validation"],
            )


class TestT15WorkflowFileReferences(unittest.TestCase):
    """T15: workflow file references every Tag-60 artifact path."""

    def test_workflow_refs(self) -> None:
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertIn("name: wirelang-spec-ots-pre-anchor-probe", text)
        self.assertIn(
            "tooling/ots/emit_wirelang_spec_ots_marker.py", text
        )
        self.assertIn(
            "tooling/ots/wirelang-spec-ots-anchor-stub.json", text
        )
        self.assertIn(
            "tests/audit/test_wirelang_spec_ots_pre_anchor_probe_tag60.py",
            text,
        )
        self.assertIn(
            "docs/operations/wirelang-spec-ots-anchor-wiring.md", text
        )
        self.assertIn("pre-activation-probe", text)
        self.assertIn("PROBE-READY", text)
        self.assertIn("PROBE-DEFECT", text)
        self.assertIn("workflow_dispatch", text)


class TestT16RunbookSectionsPresent(unittest.TestCase):
    """T16: runbook has the 5+ required sections + mirror-twin reference."""

    def test_runbook_sections(self) -> None:
        text = RUNBOOK_PATH.read_text(encoding="utf-8")
        for header in (
            "## 1. Purpose",
            "## 2. Wiring inventory",
            "## 3. Helper + stub layout",
            "## 4. Probe modes",
            "## 5. Cross-trip-wire with Tag-58 freeze-seal",
            "## 6. AR-authorisation gate",
            "## 7. Operator-Hand cutover",
            "## 8. Open items",
        ):
            self.assertIn(header, text, f"runbook missing section: {header}")
        self.assertIn("manifest-hash-ots-anchor-wiring.md", text)
        self.assertIn("KW-24", text)


class TestT17SandboxBoundaryStdlibOnly(unittest.TestCase):
    """T17: helper source imports stdlib only — no third-party imports."""

    def test_stdlib_only(self) -> None:
        text = HELPER_PATH.read_text(encoding="utf-8")
        # The helper imports argparse, datetime, hashlib, json, os, sys,
        # pathlib and typing. No third-party imports allowed.
        forbidden = (
            "import requests",
            "import urllib3",
            "import httpx",
            "import opentimestamps",
            "from opentimestamps",
            "import subprocess",
            "from subprocess",
            "import socket",
            "from socket",
        )
        for f in forbidden:
            self.assertNotIn(f, text, f"forbidden import found: {f}")


class TestT18BuildProbeVerdictDefectClassifier(unittest.TestCase):
    """T18: build_probe_verdict flips to PROBE-DEFECT iff any stage non-OK."""

    def test_classifier(self) -> None:
        ok_stages = {k: "OK" for k in HELPER.PROBE_STAGE_KEYS}
        v_ready = HELPER.build_probe_verdict(
            stages=ok_stages,
            spec_sha256="aa" * 32,
            spec_size_bytes=1,
            now_utc=FIXED_NOW,
        )
        self.assertEqual(v_ready["verdict"], "PROBE-READY")
        # Flip one stage to FAIL — verdict must turn DEFECT.
        for flip_key in HELPER.PROBE_STAGE_KEYS:
            stages = dict(ok_stages)
            stages[flip_key] = "FAIL: synthetic"
            v_def = HELPER.build_probe_verdict(
                stages=stages,
                spec_sha256="aa" * 32,
                spec_size_bytes=1,
                now_utc=FIXED_NOW,
            )
            self.assertEqual(
                v_def["verdict"],
                "PROBE-DEFECT",
                f"flipping {flip_key} did not produce DEFECT",
            )


if __name__ == "__main__":
    unittest.main()
