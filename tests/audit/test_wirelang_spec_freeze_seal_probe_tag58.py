# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""
Hermetic Tag-58 tests for the Wirelang-Spec v0.4.3 pre-cutover-
freeze-seal probe
(``tooling/audit/verify_wirelang_spec_freeze_seal.py``).

Test inventory (>= 12 hermetic, all stdlib):

  T01  helper module imports without side-effects; module-level
       constants are well-formed (VERDICT_* strings, REGEX
       patterns, default paths).
  T02  parse_frontmatter on a synthetic minimal frontmatter
       returns the expected flat string-to-string mapping; an
       absent frontmatter returns an empty dict.
  T03  Baseline.from_json_path round-trips the freeze-baseline.json
       structure: frontmatter_invariants, sha256, byte_count,
       line_count, allowlist, freeze_marker, freeze_anchor.
  T04  detect_freeze_marker reports has_drift=False when the
       synthetic spec carries the baseline frontmatter and
       has_drift=True when a single key is mutated.
  T05  diff_against_baseline: synthetic spec matching the baseline
       sha/byte/line counts returns is_intact=True; mutating one
       byte flips all three flags.
  T06  classify_added_line: a ``## Errata`` anchor classifies as
       ``errata-footer``; an inline ``<!-- typo: x -->`` comment
       classifies as ``typo-marker``; a plain content-line outside
       both classifies as ``unallowlisted``.
  T07  run_audit on a synthetic intact spec returns
       verdict=SEAL-INTACT, verdict_class=byte-for-byte-match,
       findings=().
  T08  run_audit on a synthetic spec with an appended errata-
       footer section returns verdict=SEAL-ALLOWED-DELTA,
       verdict_class=errata-footer-only, tally["unallowlisted"]=0.
  T09  run_audit on a synthetic spec with an inserted typo-marker
       returns verdict=SEAL-ALLOWED-DELTA,
       verdict_class=typo-marker-only.
  T10  run_audit on a synthetic spec with an unallowlisted edit
       (e.g. an injected new ``## 10. New normative section``)
       returns verdict=SEAL-BROKEN,
       verdict_class=unallowlisted-delta.
  T11  run_audit on a synthetic spec with a frontmatter drift
       (status flipped to ``draft``) returns verdict=SEAL-BROKEN,
       verdict_class=frontmatter-drift, even if the body is
       byte-identical apart from the frontmatter line.
  T12  SealEnvelope.to_dict round-trips through json.loads with a
       stable shape: top-level keys present, ``verdict`` is one
       of the three constants, ``tally`` keys present.
  T13  Cross-site anchor: when run against the *real* in-tree
       spec at ``wirelang/specs/wirelang-spec-v0-4-3.md`` (skip-
       if-absent), the verdict is ``SEAL-INTACT`` with byte-for-
       byte match — i.e. the in-tree spec on the Tag-58 PR
       matches the freeze-baseline.json that ships in the same
       PR.
  T14  CLI smoke: argparse parses ``--enforce`` and ``--tag``,
       and main() returns 0 on a synthetic intact fixture even
       in enforce-mode.

All fixtures (except T13's real-world anchor) are synthesised in
``tmp_path``. No network, no real clone, no PyYAML, no jsonschema.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import unittest


# --------------------------------------------------------------- #
# Helper import (path-driven so tests work both from repo root    #
# and from a pytest/unittest invocation in tests/audit/)          #
# --------------------------------------------------------------- #


_HELPER_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "tooling"
    / "audit"
    / "verify_wirelang_spec_freeze_seal.py"
)


def _load_helper():
    spec = importlib.util.spec_from_file_location(
        "verify_wirelang_spec_freeze_seal_tag58", _HELPER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_M = _load_helper()


# --------------------------------------------------------------- #
# Synthetic fixture builder                                       #
# --------------------------------------------------------------- #


_FRONTMATTER_INTACT = """\
<!--
SPDX-License-Identifier: CC-BY-4.0
-->

---
spec: wirelang
version: 0.4.3
status: pre-cutover-freeze
freeze-marker: kw-24-cutover-gate
freeze-anchor: persona-engine-0.5.2-final-pre-cutover
---

# Wirelang Specification v0.4.3 (synthetic-fixture)

## 1. Scope of v0.4.3

A synthetic body line.

## 2. Conformance keywords

Another synthetic body line.

## 9. Citation pointers

- Synthetic citation.

— Reza
"""


def _hash_of(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _make_synthetic_baseline(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path, str]:
    """Write a synthetic spec + freeze-baseline.json into tmp_path
    and return ``(spec_path, baseline_path, spec_text)``."""
    spec_path = tmp_path / "wirelang-spec-v0-4-3.md"
    baseline_path = tmp_path / "freeze-baseline.json"
    text = _FRONTMATTER_INTACT
    spec_path.write_text(text, encoding="utf-8")
    sha = _hash_of(text)
    baseline_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "spec": "wirelang",
                "spec_version": "0.4.3",
                "spec_path": str(spec_path),
                "freeze_marker": "kw-24-cutover-gate",
                "freeze_anchor": "persona-engine-0.5.2-final-pre-cutover",
                "freeze_status": "pre-cutover-freeze",
                "cutover_window": {"starts": "2026-06-09T00:00:00Z"},
                "baseline": {
                    "sha256": sha,
                    "byte_count": len(text.encode("utf-8")),
                    "line_count": text.count("\n"),
                },
                "frontmatter_invariants": {
                    "version": "0.4.3",
                    "status": "pre-cutover-freeze",
                    "freeze-marker": "kw-24-cutover-gate",
                    "freeze-anchor": "persona-engine-0.5.2-final-pre-cutover",
                },
                "section_headers": [
                    "## 1. Scope of v0.4.3",
                    "## 2. Conformance keywords",
                    "## 9. Citation pointers",
                ],
                "allowlist": {
                    "modes": ["errata-footer", "typo-marker"],
                    "errata_footer": {},
                    "typo_marker": {},
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return spec_path, baseline_path, text


# --------------------------------------------------------------- #
# Tests                                                            #
# --------------------------------------------------------------- #


class T01HelperModuleContract(unittest.TestCase):
    def test_module_loads(self) -> None:
        self.assertIsNotNone(_M)

    def test_verdict_constants(self) -> None:
        self.assertEqual(_M.VERDICT_INTACT, "SEAL-INTACT")
        self.assertEqual(_M.VERDICT_ALLOWED, "SEAL-ALLOWED-DELTA")
        self.assertEqual(_M.VERDICT_BROKEN, "SEAL-BROKEN")
        self.assertEqual(
            set(_M.VERDICTS),
            {"SEAL-INTACT", "SEAL-ALLOWED-DELTA", "SEAL-BROKEN"},
        )

    def test_regex_patterns_compiled(self) -> None:
        self.assertIsNotNone(_M.TYPO_MARKER_RE.search("<!-- typo: foo -->"))
        self.assertIsNotNone(_M.ERRATA_ANCHOR_RE.match("## Errata"))
        self.assertIsNotNone(_M.ERRATA_MARKER_RE.match("### ERR-S1 something"))


class T02FrontmatterParser(unittest.TestCase):
    def test_minimal_frontmatter(self) -> None:
        text = "---\nspec: wirelang\nversion: 0.4.3\n---\n\nBody."
        fm = _M.parse_frontmatter(text)
        self.assertEqual(fm.get("spec"), "wirelang")
        self.assertEqual(fm.get("version"), "0.4.3")

    def test_absent_frontmatter_returns_empty(self) -> None:
        text = "Just a body, no frontmatter at all."
        self.assertEqual(_M.parse_frontmatter(text), {})


class T03BaselineRoundtrip(unittest.TestCase):
    def test_baseline_loads(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            _, baseline_path, _ = _make_synthetic_baseline(tmp_path)
            baseline = _M.Baseline.from_json_path(baseline_path)
            self.assertEqual(baseline.freeze_status, "pre-cutover-freeze")
            self.assertEqual(baseline.freeze_marker, "kw-24-cutover-gate")
            self.assertEqual(
                baseline.freeze_anchor,
                "persona-engine-0.5.2-final-pre-cutover",
            )
            self.assertIn("version", baseline.frontmatter_invariants)


class T04FreezeMarkerDetect(unittest.TestCase):
    def test_intact_frontmatter(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, _ = _make_synthetic_baseline(tmp_path)
            baseline = _M.Baseline.from_json_path(baseline_path)
            fm = _M.detect_freeze_marker(
                spec_path.read_text(encoding="utf-8"), baseline
            )
            self.assertTrue(fm.found)
            self.assertFalse(fm.has_drift)

    def test_drifted_status_field(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, _ = _make_synthetic_baseline(tmp_path)
            text = spec_path.read_text(encoding="utf-8").replace(
                "status: pre-cutover-freeze", "status: draft"
            )
            baseline = _M.Baseline.from_json_path(baseline_path)
            fm = _M.detect_freeze_marker(text, baseline)
            self.assertTrue(fm.found)
            self.assertTrue(fm.has_drift)
            drift_keys = {d[0] for d in fm.drift}
            self.assertIn("status", drift_keys)


class T05HashDiff(unittest.TestCase):
    def test_intact(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, text = _make_synthetic_baseline(tmp_path)
            baseline = _M.Baseline.from_json_path(baseline_path)
            hs = _M.diff_against_baseline(text, len(text.encode("utf-8")), baseline)
            self.assertTrue(hs.is_intact)
            self.assertTrue(hs.sha256_matches)
            self.assertTrue(hs.byte_count_matches)
            self.assertTrue(hs.line_count_matches)

    def test_mutated(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, text = _make_synthetic_baseline(tmp_path)
            baseline = _M.Baseline.from_json_path(baseline_path)
            mutated = text + "\nAn extra appended line.\n"
            hs = _M.diff_against_baseline(
                mutated, len(mutated.encode("utf-8")), baseline
            )
            self.assertFalse(hs.is_intact)
            self.assertFalse(hs.sha256_matches)
            self.assertFalse(hs.byte_count_matches)
            self.assertFalse(hs.line_count_matches)


class T06AllowlistClassify(unittest.TestCase):
    def test_errata_anchor(self) -> None:
        cls, _ = _M.classify_added_line("## Errata", in_errata_section=False)
        self.assertEqual(cls, "errata-footer")

    def test_typo_marker(self) -> None:
        cls, _ = _M.classify_added_line(
            "Some content. <!-- typo: corrected -->",
            in_errata_section=False,
        )
        self.assertEqual(cls, "typo-marker")

    def test_unallowlisted_content_line(self) -> None:
        cls, _ = _M.classify_added_line(
            "## 10. New normative section",
            in_errata_section=False,
        )
        self.assertEqual(cls, "unallowlisted")


class T07RunAuditIntact(unittest.TestCase):
    def test_intact_spec(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, _ = _make_synthetic_baseline(tmp_path)
            envelope = _M.run_audit(
                spec_path=spec_path, baseline_path=baseline_path
            )
            self.assertEqual(envelope.verdict, "SEAL-INTACT")
            self.assertEqual(envelope.verdict_class, "byte-for-byte-match")
            self.assertEqual(envelope.findings, ())


class T08RunAuditErrataFooter(unittest.TestCase):
    def test_appended_errata_footer(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, text = _make_synthetic_baseline(tmp_path)
            # Append an errata-footer section between citations and signoff.
            mutated = text.replace(
                "— Reza",
                "## Errata\n\n### ERR-S1 path-rename\n\nCorrected path: `foo/bar`.\n\n— Reza",
            )
            spec_path.write_text(mutated, encoding="utf-8")
            envelope = _M.run_audit(
                spec_path=spec_path,
                baseline_path=baseline_path,
                baseline_text=text,
            )
            self.assertEqual(envelope.verdict, "SEAL-ALLOWED-DELTA")
            self.assertEqual(envelope.verdict_class, "errata-footer-only")
            self.assertEqual(envelope.tally["unallowlisted"], 0)
            self.assertGreater(envelope.tally["errata-footer"], 0)


class T09RunAuditTypoMarker(unittest.TestCase):
    def test_inserted_typo_marker(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, text = _make_synthetic_baseline(tmp_path)
            mutated = text.replace(
                "A synthetic body line.",
                "A synthetic body line. <!-- typo: fixed -->",
            )
            spec_path.write_text(mutated, encoding="utf-8")
            envelope = _M.run_audit(
                spec_path=spec_path,
                baseline_path=baseline_path,
                baseline_text=text,
            )
            self.assertEqual(envelope.verdict, "SEAL-ALLOWED-DELTA")
            self.assertEqual(envelope.verdict_class, "typo-marker-only")
            self.assertEqual(envelope.tally["unallowlisted"], 0)
            self.assertGreater(envelope.tally["typo-marker"], 0)


class T10RunAuditUnallowlisted(unittest.TestCase):
    def test_injected_new_section(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, text = _make_synthetic_baseline(tmp_path)
            mutated = text.replace(
                "## 9. Citation pointers",
                "## 10. New normative section\n\nA new MUST clause appears here.\n\n## 9. Citation pointers",
            )
            spec_path.write_text(mutated, encoding="utf-8")
            envelope = _M.run_audit(
                spec_path=spec_path,
                baseline_path=baseline_path,
                baseline_text=text,
            )
            self.assertEqual(envelope.verdict, "SEAL-BROKEN")
            self.assertEqual(envelope.verdict_class, "unallowlisted-delta")
            self.assertGreater(envelope.tally["unallowlisted"], 0)


class T11RunAuditFrontmatterDrift(unittest.TestCase):
    def test_status_flipped_to_draft(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, text = _make_synthetic_baseline(tmp_path)
            mutated = text.replace(
                "status: pre-cutover-freeze", "status: draft"
            )
            spec_path.write_text(mutated, encoding="utf-8")
            envelope = _M.run_audit(
                spec_path=spec_path, baseline_path=baseline_path
            )
            self.assertEqual(envelope.verdict, "SEAL-BROKEN")
            self.assertEqual(envelope.verdict_class, "frontmatter-drift")


class T12EnvelopeShape(unittest.TestCase):
    def test_envelope_round_trips(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, _ = _make_synthetic_baseline(tmp_path)
            envelope = _M.run_audit(
                spec_path=spec_path, baseline_path=baseline_path
            )
            d = envelope.to_dict()
            self.assertIn("verdict", d)
            self.assertIn("verdict_class", d)
            self.assertIn("frontmatter", d)
            self.assertIn("hash", d)
            self.assertIn("findings", d)
            self.assertIn("tally", d)
            self.assertIn(d["verdict"], {"SEAL-INTACT", "SEAL-ALLOWED-DELTA", "SEAL-BROKEN"})
            # Tally keys present.
            for k in ("errata-footer", "typo-marker", "unallowlisted", "removed"):
                self.assertIn(k, d["tally"])
            # JSON round-trip.
            again = json.loads(json.dumps(d))
            self.assertEqual(again["verdict"], d["verdict"])


class T13CrossSiteAnchor(unittest.TestCase):
    def test_real_in_tree_spec_is_intact(self) -> None:
        spec_path = _M.DEFAULT_SPEC_PATH
        baseline_path = _M.DEFAULT_BASELINE_PATH
        if not spec_path.exists() or not baseline_path.exists():
            self.skipTest("real-world spec or baseline not present")
        envelope = _M.run_audit(
            spec_path=spec_path, baseline_path=baseline_path
        )
        self.assertEqual(envelope.verdict, "SEAL-INTACT")
        self.assertEqual(envelope.verdict_class, "byte-for-byte-match")
        self.assertEqual(envelope.tally["unallowlisted"], 0)


class T14CliSmoke(unittest.TestCase):
    def test_cli_returns_zero_on_intact_fixture(self) -> None:
        import io
        import tempfile
        from contextlib import redirect_stdout

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            spec_path, baseline_path, _ = _make_synthetic_baseline(tmp_path)
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = _M.main(
                    [
                        "--spec",
                        str(spec_path),
                        "--baseline",
                        str(baseline_path),
                        "--enforce",
                    ]
                )
            self.assertEqual(rc, 0)
            # Output must be valid JSON with the expected verdict.
            payload = json.loads(buf.getvalue())
            self.assertEqual(payload["verdict"], "SEAL-INTACT")


if __name__ == "__main__":  # pragma: no cover
    unittest.main(verbosity=2)
