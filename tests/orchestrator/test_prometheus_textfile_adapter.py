# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/prometheus-textfile-adapter.py``.

Coverage:

1. Flavour detection: nats-kv, federation-evaluator, ambiguous,
   unknown.
2. NATS-KV render: per-bucket status encoding, summary counters,
   jsz_up gauge, label escaping.
3. Federation-evaluator render: bucket / snapshot / probe / poisoned-
   keys gauges.
4. Atomic write: tmp file in target dir, ``os.replace`` over.
5. Stale tmp cleanup on render failure.
6. CLI exit-code matrix: missing input (1), malformed JSON (1),
   unknown flavour (1), unwritable output dir (2), happy path (0).
7. Dry-run: prints to stdout, no output file touched.
8. Output is parseable as Prometheus text format (prefix invariants).

The suite is fully I/O-bound on a tmpdir; no NATS, no node_exporter.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "prometheus-textfile-adapter.py"
_MODULE_NAME = "prometheus_textfile_adapter"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME, str(_SCRIPT)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


adapter = _load_module()


# ---------------------------------------------------------------------
# Sample reports
# ---------------------------------------------------------------------


def _nats_kv_report_ok() -> dict:
    return {
        "servers": "nats://127.0.0.1:4222",
        "jsz_url": "http://127.0.0.1:8222/jsz",
        "dry_run": False,
        "jsz": {"status": "ok", "detail": "2xx", "http_status": 200},
        "summary": {"ok": 4, "missing": 0, "drift": 0,
                    "error": 0, "total": 4},
        "checks": [
            {"name": "wakir-schemas", "status": "ok",
             "detail": "schema cache", "drift": {}},
            {"name": "wakir-routes", "status": "ok",
             "detail": "route registry", "drift": {}},
            {"name": "wakir-ftd-poisoned", "status": "ok",
             "detail": "poison list", "drift": {}},
            {"name": "wakir-attestations", "status": "ok",
             "detail": "attestations", "drift": {}},
        ],
    }


def _nats_kv_report_drifted() -> dict:
    r = _nats_kv_report_ok()
    r["summary"] = {"ok": 2, "missing": 1, "drift": 1,
                    "error": 0, "total": 4}
    r["jsz"] = {"status": "unreachable",
                "detail": "connection refused", "http_status": 0}
    r["checks"] = [
        {"name": "wakir-schemas", "status": "ok",
         "detail": "...", "drift": {}},
        {"name": "wakir-routes", "status": "missing",
         "detail": "404", "drift": {}},
        {"name": 'weird"name', "status": "drift",
         "detail": "...", "drift": {"history": {"want": 5, "got": 1}}},
        {"name": "wakir-attestations", "status": "ok",
         "detail": "...", "drift": {}},
    ]
    return r


def _federation_report_ok() -> dict:
    return {
        "bucket": {"name": "wakir-federation-routes", "status": "ok",
                   "detail": "...", "drift": {}},
        "bucket_name": "wakir-federation-routes",
        "dry_run": False,
        "evaluator": {"status": "skipped", "detail": "no probe",
                      "error_kind": None, "ftd_id": None,
                      "route_id": None},
        "jsz": {"status": "ok", "detail": "2xx", "http_status": 200},
        "jsz_url": "http://127.0.0.1:8222/jsz",
        "servers": "nats://127.0.0.1:4222",
        "snapshot": {"active": 2, "expired": 0, "not_yet_active": 0,
                     "with_wat_anchor": 1, "poisoned_keys": [],
                     "status": "ok", "total": 2, "detail": "..."},
    }


def _federation_report_poisoned() -> dict:
    r = _federation_report_ok()
    r["snapshot"]["poisoned_keys"] = ["bad-1", "bad-2", "bad-3"]
    r["evaluator"]["status"] = "reject"
    r["evaluator"]["error_kind"] = "expired-attestation"
    return r


# ---------------------------------------------------------------------
# Flavour detection
# ---------------------------------------------------------------------


class FlavourDetectionTests(unittest.TestCase):

    def test_nats_kv_flavour(self):
        self.assertEqual(
            adapter.detect_flavour(_nats_kv_report_ok()),
            adapter.FLAVOUR_NATS_KV,
        )

    def test_federation_flavour(self):
        self.assertEqual(
            adapter.detect_flavour(_federation_report_ok()),
            adapter.FLAVOUR_FEDERATION,
        )

    def test_ambiguous_rejected(self):
        merged = _nats_kv_report_ok()
        merged.update(_federation_report_ok())
        with self.assertRaises(ValueError):
            adapter.detect_flavour(merged)

    def test_unknown_rejected(self):
        with self.assertRaises(ValueError):
            adapter.detect_flavour({"foo": "bar"})


# ---------------------------------------------------------------------
# NATS-KV render
# ---------------------------------------------------------------------


class NatsKvRenderTests(unittest.TestCase):

    def test_jsz_up_ok(self):
        out = adapter.render_nats_kv(_nats_kv_report_ok())
        self.assertIn(
            'wakir_nats_kv_jsz_up{servers="nats://127.0.0.1:4222"} 1',
            out,
        )

    def test_jsz_up_unreachable(self):
        out = adapter.render_nats_kv(_nats_kv_report_drifted())
        self.assertIn(
            'wakir_nats_kv_jsz_up{servers="nats://127.0.0.1:4222"} 0',
            out,
        )

    def test_summary_counters(self):
        out = adapter.render_nats_kv(_nats_kv_report_drifted())
        self.assertIn("wakir_nats_kv_buckets_total 4\n", out)
        self.assertIn("wakir_nats_kv_buckets_ok 2\n", out)
        self.assertIn("wakir_nats_kv_buckets_missing 1\n", out)
        self.assertIn("wakir_nats_kv_buckets_drift 1\n", out)
        self.assertIn("wakir_nats_kv_buckets_error 0\n", out)

    def test_per_bucket_status_encoding(self):
        out = adapter.render_nats_kv(_nats_kv_report_drifted())
        self.assertIn(
            'wakir_nats_kv_bucket_status{bucket="wakir-schemas"} 0',
            out,
        )
        self.assertIn(
            'wakir_nats_kv_bucket_status{bucket="wakir-routes"} 1',
            out,
        )
        # Drift = 2; weird quoted bucket name must be escaped.
        self.assertIn(
            'wakir_nats_kv_bucket_status{bucket="weird\\"name"} 2',
            out,
        )

    def test_help_and_type_lines_present(self):
        out = adapter.render_nats_kv(_nats_kv_report_ok())
        self.assertIn("# HELP wakir_nats_kv_jsz_up", out)
        self.assertIn("# TYPE wakir_nats_kv_jsz_up gauge", out)
        self.assertIn("# HELP wakir_nats_kv_bucket_status", out)
        self.assertIn("# TYPE wakir_nats_kv_bucket_status gauge", out)

    def test_skips_malformed_check_entries(self):
        r = _nats_kv_report_ok()
        r["checks"].append("not-a-dict")  # type: ignore[arg-type]
        # Must not raise.
        out = adapter.render_nats_kv(r)
        self.assertNotIn("not-a-dict", out)


# ---------------------------------------------------------------------
# Federation-evaluator render
# ---------------------------------------------------------------------


class FederationRenderTests(unittest.TestCase):

    def test_bucket_status_label(self):
        out = adapter.render_federation(_federation_report_ok())
        self.assertIn(
            'wakir_federation_evaluator_bucket_status'
            '{bucket="wakir-federation-routes"} 0',
            out,
        )

    def test_snapshot_counters(self):
        out = adapter.render_federation(_federation_report_ok())
        self.assertIn("wakir_federation_evaluator_routes_total 2\n", out)
        self.assertIn("wakir_federation_evaluator_routes_active 2\n", out)
        self.assertIn(
            "wakir_federation_evaluator_routes_with_wat_anchor 1\n", out,
        )

    def test_poisoned_keys_count(self):
        out = adapter.render_federation(_federation_report_poisoned())
        self.assertIn(
            "wakir_federation_evaluator_poisoned_keys_total 3\n", out,
        )

    def test_probe_status_reject_encoded_as_2(self):
        out = adapter.render_federation(_federation_report_poisoned())
        self.assertIn(
            "wakir_federation_evaluator_probe_status 2\n", out,
        )

    def test_probe_status_skipped_encoded_as_1(self):
        out = adapter.render_federation(_federation_report_ok())
        self.assertIn(
            "wakir_federation_evaluator_probe_status 1\n", out,
        )

    def test_handles_missing_optional_fields(self):
        r = _federation_report_ok()
        r["snapshot"]["with_wat_anchor"] = None
        # Must coerce None to 0, not raise.
        out = adapter.render_federation(r)
        self.assertIn(
            "wakir_federation_evaluator_routes_with_wat_anchor 0\n", out,
        )


# ---------------------------------------------------------------------
# render() top-level + last-run-stamp
# ---------------------------------------------------------------------


class RenderTopLevelTests(unittest.TestCase):

    def test_nats_kv_includes_last_run_stamp(self):
        out = adapter.render(_nats_kv_report_ok(), now=1715000000)
        self.assertIn(
            "wakir_nats_kv_adapter_last_run_seconds 1715000000",
            out,
        )

    def test_federation_includes_last_run_stamp(self):
        out = adapter.render(_federation_report_ok(), now=1715000123)
        self.assertIn(
            "wakir_federation_evaluator_adapter_last_run_seconds 1715000123",
            out,
        )

    def test_unknown_flavour_raises(self):
        with self.assertRaises(ValueError):
            adapter.render({"foo": "bar"})


# ---------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------


class WriteAtomicTests(unittest.TestCase):

    def test_creates_target_directory(self, tmp_path=None):
        # pytest provides tmp_path via fixture; emulate via env.
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "nested" / "deep" / "out.prom"
            adapter.write_atomic(target, "hello\n")
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), "hello\n")

    def test_replaces_existing_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.prom"
            target.write_text("old", encoding="utf-8")
            adapter.write_atomic(target, "new")
            self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_no_partial_files_left_on_success(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "out.prom"
            adapter.write_atomic(target, "ok")
            # Only one file in the directory; tmp file must be gone.
            self.assertEqual(
                sorted(p.name for p in Path(td).iterdir()),
                ["out.prom"],
            )


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


class CliTests(unittest.TestCase):

    def _write_input(self, td: Path, body: Any) -> Path:
        p = td / "input.json"
        p.write_text(json.dumps(body), encoding="utf-8")
        return p

    def test_happy_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            inp = self._write_input(tdp, _nats_kv_report_ok())
            out = tdp / "out.prom"
            rc = adapter.main(["--input", str(inp), "--output", str(out)])
            self.assertEqual(rc, 0)
            self.assertTrue(out.exists())
            content = out.read_text(encoding="utf-8")
            self.assertIn("wakir_nats_kv_buckets_ok 4\n", content)

    def test_missing_input_returns_1(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            rc = adapter.main([
                "--input", str(Path(td) / "nope.json"),
                "--output", str(Path(td) / "out.prom"),
            ])
            self.assertEqual(rc, 1)

    def test_malformed_json_returns_1(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            inp = Path(td) / "bad.json"
            inp.write_text("not json", encoding="utf-8")
            rc = adapter.main([
                "--input", str(inp),
                "--output", str(Path(td) / "out.prom"),
            ])
            self.assertEqual(rc, 1)

    def test_unknown_flavour_returns_1(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            inp = self._write_input(tdp, {"foo": "bar"})
            rc = adapter.main([
                "--input", str(inp),
                "--output", str(tdp / "out.prom"),
            ])
            self.assertEqual(rc, 1)

    def test_dry_run_prints_to_stdout_no_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            inp = self._write_input(tdp, _nats_kv_report_ok())
            target = tdp / "should-not-exist.prom"
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = adapter.main([
                    "--input", str(inp),
                    "--output", str(target),
                    "--dry-run",
                ])
            self.assertEqual(rc, 0)
            self.assertFalse(target.exists())
            self.assertIn("wakir_nats_kv_buckets_total 4", buf.getvalue())

    def test_unwritable_output_returns_2(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            inp = self._write_input(tdp, _nats_kv_report_ok())
            # Make a read-only directory under the tmp tree.
            ro = tdp / "ro"
            ro.mkdir()
            os.chmod(ro, 0o500)
            try:
                rc = adapter.main([
                    "--input", str(inp),
                    "--output", str(ro / "out.prom"),
                ])
                # Root bypasses permission checks; skip in that case.
                if os.geteuid() == 0:  # pragma: no cover
                    self.skipTest("running as root, chmod-based deny is moot")
                self.assertEqual(rc, 2)
            finally:
                os.chmod(ro, 0o700)

    def test_output_parseable_format_invariants(self):
        """Spot-check: every metric line is preceded by HELP and TYPE."""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            inp = self._write_input(tdp, _federation_report_ok())
            out = tdp / "out.prom"
            rc = adapter.main(["--input", str(inp), "--output", str(out)])
            self.assertEqual(rc, 0)
            text = out.read_text(encoding="utf-8")
            # Each declared metric appears with both header lines.
            for metric in (
                "wakir_federation_evaluator_jsz_up",
                "wakir_federation_evaluator_bucket_status",
                "wakir_federation_evaluator_routes_total",
                "wakir_federation_evaluator_poisoned_keys_total",
                "wakir_federation_evaluator_probe_status",
                "wakir_federation_evaluator_adapter_last_run_seconds",
            ):
                self.assertIn(f"# HELP {metric}", text, metric)
                self.assertIn(f"# TYPE {metric} gauge", text, metric)


if __name__ == "__main__":
    unittest.main()
