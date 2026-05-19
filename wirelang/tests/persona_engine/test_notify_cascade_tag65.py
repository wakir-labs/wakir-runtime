# REUSE-IgnoreStart
# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
# REUSE-IgnoreEnd
"""Tag-65 - Cutover-Day-Morgen Notify-Cascade tests (Selin).

The Tag-65 notify-cascade wires the Tag-64 Cutover-Day-Morgen
Auto-Scheduler verdict into Noa's ntfy-routing table by emitting a
ntfy-shaped AUDIT-ONLY notify-cascade payload that operator-hand
reads and (manually) curl-POSTs to ntfy.sh after review.

This hermetic test-suite pins:

* the byte-shape of the cascade constants on the Tag-64 aggregator
  helper (TOPIC_BLOCK / TOPIC_CAUTION / PRIORITY_MAP / TAGS_MAP /
  KIND / AUDIT_ONLY),
* the ``should_emit_notify_cascade`` decision rule (BLOCK always,
  CAUTION transition-only, READY never, unknown never),
* the ``build_notify_cascade_payload`` byte-shape (ntfy.sh contract
  fields + verdict_summary + audit-only marker + operator_curl_hint),
* the BLOCK-fires-every-run + CAUTION-transition + READY-suppressed
  + stable-CAUTION-suppressed end-to-end CLI behaviour,
* the workflow byte-shape at
  ``.github/workflows/cutover-day-morgen-notify-cascade.yml``
  (audit-only invariant: no curl, no outbound HTTPS, no secrets).

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC, no ntfy POST.
* No subprocess (aggregator imported, not shelled).
* No filesystem writes outside ``tempfile``.
* Deterministic - no clock-sensitive assertions.

Scope discipline (Selin)
------------------------
This file does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), identity-
substrate design (Reza-Domaene, Zone-L), or container-infra
(Kai-Domaene, Zone-J). It only asserts the cascade helper +
workflow byte-shape the Tag-65 substrate stakes.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
AGGREGATOR_PATH = (
    REPO_ROOT / "tooling" / "ci" / "aggregate_cutover_day_morgen_verdict.py"
)
WORKFLOW_PATH = (
    REPO_ROOT
    / ".github"
    / "workflows"
    / "cutover-day-morgen-notify-cascade.yml"
)


def _load_aggregator():
    """Import the aggregator helper as a fresh module."""
    spec = importlib.util.spec_from_file_location(
        "tag65_aggregator_under_test", AGGREGATOR_PATH
    )
    assert spec is not None and spec.loader is not None, AGGREGATOR_PATH
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_envelope(verdict: str, *, iso_week: int = 24) -> dict:
    """Build a minimal Tag-64 aggregator envelope for cascade tests."""
    if verdict == "CUTOVER-DAY-MORGEN-READY":
        step_results = {
            "engine_composite": "green",
            "pyramide_composite": "green",
            "e2e_smoke": "green",
        }
        counts = {"green": 3, "yellow": 0, "red": 0}
        failed: list[str] = []
        notes: dict[str, str] = {}
    elif verdict == "CUTOVER-DAY-MORGEN-CAUTION":
        step_results = {
            "engine_composite": "green",
            "pyramide_composite": "yellow",
            "e2e_smoke": "green",
        }
        counts = {"green": 2, "yellow": 1, "red": 0}
        failed = ["pyramide_composite"]
        notes = {"pyramide_composite": "pyramide_composite: verdict='ACCEPTANCE-PYRAMIDE-DRIFT'"}
    elif verdict == "CUTOVER-DAY-MORGEN-BLOCK":
        step_results = {
            "engine_composite": "red",
            "pyramide_composite": "green",
            "e2e_smoke": "yellow",
        }
        counts = {"green": 1, "yellow": 1, "red": 1}
        failed = ["engine_composite", "e2e_smoke"]
        notes = {
            "engine_composite": "engine_composite: verdict='PRE-CUTOVER-DEFECT'",
            "e2e_smoke": "e2e_smoke: verdict='E2E-DRIFT'",
        }
    else:
        raise AssertionError(f"unsupported verdict for fixture: {verdict}")
    return {
        "schema_version": 1,
        "workflow": "cutover-day-morgen-auto-scheduler",
        "tag": "tag-64",
        "emitted_at_utc": "2026-06-08T06:00:00+00:00",
        "github_run_id": "9999999999",
        "github_sha": "deadbeef" * 5,
        "github_ref": "refs/heads/main",
        "verdict": verdict,
        "step_results": step_results,
        "failed_steps": failed,
        "per_substrate_notes": notes,
        "counts": counts,
        "window": {
            "iso_week": iso_week,
            "in_cutover_window": iso_week in (24, 25, 26, 27),
            "cutover_iso_weeks": [24, 25, 26, 27],
        },
        "input_verdicts": {
            "engine_composite": "PRE-CUTOVER-READY",
            "pyramide_composite": "ACCEPTANCE-PYRAMIDE-READY",
            "e2e_smoke": "E2E-READY",
        },
        "decision_rule": {
            "ready": "all three top-level verdicts green",
            "caution": "at least one yellow, zero red",
            "block": "at least one red, OR any envelope missing",
        },
    }


class Tag65CascadeConstantsTests(unittest.TestCase):
    """Pin the cascade-constant byte-shape on the aggregator."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    # ---- 01 Topic constants -------------------------------------------------

    def test_01_topic_constants_exact_strings(self) -> None:
        """Topics route BLOCK -> ar-hand-critical, CAUTION -> ar-hand."""
        self.assertEqual(
            self.agg.NOTIFY_CASCADE_TOPIC_BLOCK, "wakir-ar-hand-critical"
        )
        self.assertEqual(
            self.agg.NOTIFY_CASCADE_TOPIC_CAUTION, "wakir-ar-hand"
        )

    # ---- 02 Priority map ----------------------------------------------------

    def test_02_priority_map_block_p5_caution_p4(self) -> None:
        """Priority map: BLOCK=5 (max), CAUTION=4. READY absent (never fires)."""
        self.assertEqual(
            self.agg.NOTIFY_CASCADE_PRIORITY_MAP["CUTOVER-DAY-MORGEN-BLOCK"], 5
        )
        self.assertEqual(
            self.agg.NOTIFY_CASCADE_PRIORITY_MAP["CUTOVER-DAY-MORGEN-CAUTION"], 4
        )
        self.assertNotIn(
            "CUTOVER-DAY-MORGEN-READY", self.agg.NOTIFY_CASCADE_PRIORITY_MAP
        )

    # ---- 03 Tags map --------------------------------------------------------

    def test_03_tags_map_block_rotating_light_caution_warning(self) -> None:
        """Tags route BLOCK -> rotating_light, CAUTION -> warning."""
        block_tags = self.agg.NOTIFY_CASCADE_TAGS_MAP["CUTOVER-DAY-MORGEN-BLOCK"]
        caution_tags = self.agg.NOTIFY_CASCADE_TAGS_MAP[
            "CUTOVER-DAY-MORGEN-CAUTION"
        ]
        self.assertEqual(block_tags, ["rotating_light", "cutover-day-morgen"])
        self.assertEqual(caution_tags, ["warning", "cutover-day-morgen"])

    # ---- 04 Audit-only marker -----------------------------------------------

    def test_04_audit_only_marker_true(self) -> None:
        """The aggregator NEVER fires real notifications - audit-only."""
        self.assertTrue(self.agg.NOTIFY_CASCADE_AUDIT_ONLY)
        self.assertEqual(
            self.agg.NOTIFY_CASCADE_KIND,
            "cutover-day-morgen-notify-cascade-payload",
        )


class Tag65ShouldEmitDecisionTests(unittest.TestCase):
    """Pin the should_emit_notify_cascade decision rule."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    # ---- 05 BLOCK fires every run -------------------------------------------

    def test_05_block_fires_every_run(self) -> None:
        """BLOCK fires regardless of prev_verdict (forensic trail)."""
        for prev in (
            None,
            "CUTOVER-DAY-MORGEN-READY",
            "CUTOVER-DAY-MORGEN-CAUTION",
            "CUTOVER-DAY-MORGEN-BLOCK",
        ):
            self.assertTrue(
                self.agg.should_emit_notify_cascade(
                    "CUTOVER-DAY-MORGEN-BLOCK", prev
                ),
                f"BLOCK should fire with prev_verdict={prev!r}",
            )

    # ---- 06 CAUTION transition-only -----------------------------------------

    def test_06_caution_fires_on_transition_only(self) -> None:
        """CAUTION fires only when prev_verdict != CAUTION (transition rule)."""
        # Transition cases: fires
        for prev in (None, "CUTOVER-DAY-MORGEN-READY", "CUTOVER-DAY-MORGEN-BLOCK"):
            self.assertTrue(
                self.agg.should_emit_notify_cascade(
                    "CUTOVER-DAY-MORGEN-CAUTION", prev
                ),
                f"CAUTION transition from prev={prev!r} should fire",
            )
        # Stable case: suppressed
        self.assertFalse(
            self.agg.should_emit_notify_cascade(
                "CUTOVER-DAY-MORGEN-CAUTION", "CUTOVER-DAY-MORGEN-CAUTION"
            ),
            "stable CAUTION must NOT fire (anti-spam)",
        )

    # ---- 07 READY never fires -----------------------------------------------

    def test_07_ready_never_fires(self) -> None:
        """READY never fires regardless of prev_verdict."""
        for prev in (
            None,
            "CUTOVER-DAY-MORGEN-READY",
            "CUTOVER-DAY-MORGEN-CAUTION",
            "CUTOVER-DAY-MORGEN-BLOCK",
        ):
            self.assertFalse(
                self.agg.should_emit_notify_cascade(
                    "CUTOVER-DAY-MORGEN-READY", prev
                ),
                f"READY should NOT fire with prev_verdict={prev!r}",
            )

    # ---- 08 Unknown verdict defensive default --------------------------------

    def test_08_unknown_verdict_defensive_default_no_fire(self) -> None:
        """Unknown verdict tokens must NOT fire (defensive)."""
        for unknown in ("CUTOVER-DAY-MORGEN-UNKNOWN", "", "BLOCK", "block"):
            self.assertFalse(
                self.agg.should_emit_notify_cascade(unknown, None),
                f"unknown verdict {unknown!r} must NOT fire",
            )


class Tag65CascadePayloadShapeTests(unittest.TestCase):
    """Pin the build_notify_cascade_payload byte-shape."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    # ---- 09 BLOCK payload shape ---------------------------------------------

    def test_09_block_payload_full_ntfy_shape(self) -> None:
        """BLOCK payload carries the full ntfy.sh-publish-as-JSON contract."""
        envelope = _build_envelope("CUTOVER-DAY-MORGEN-BLOCK", iso_week=25)
        payload = self.agg.build_notify_cascade_payload(envelope)
        self.assertIsNotNone(payload)
        assert payload is not None  # narrow type for mypy
        # Required ntfy.sh fields
        self.assertEqual(payload["topic"], "wakir-ar-hand-critical")
        self.assertEqual(payload["priority"], 5)
        self.assertIn("rotating_light", payload["tags"])
        self.assertIn("cutover-day-morgen", payload["tags"])
        self.assertIn("CUTOVER-DAY-MORGEN-BLOCK", payload["title"])
        self.assertIn("KW-25", payload["title"])
        self.assertIn("engine_composite=red", payload["message"])
        self.assertIn("e2e_smoke=yellow", payload["message"])
        # Audit-only marker + kind
        self.assertTrue(payload["audit_only"])
        self.assertEqual(
            payload["kind"], "cutover-day-morgen-notify-cascade-payload"
        )
        # Verdict summary preserves forensic data
        self.assertEqual(
            payload["verdict_summary"]["verdict"], "CUTOVER-DAY-MORGEN-BLOCK"
        )
        self.assertEqual(payload["verdict_summary"]["iso_week"], 25)
        self.assertEqual(
            payload["verdict_summary"]["failed_steps"],
            ["engine_composite", "e2e_smoke"],
        )
        # Operator-hand fires the curl, NOT the workflow.
        self.assertIn("curl", payload["operator_curl_hint"])
        self.assertIn("ntfy.sh", payload["operator_curl_hint"])

    # ---- 10 CAUTION transition payload shape --------------------------------

    def test_10_caution_transition_payload_shape(self) -> None:
        """CAUTION transition payload carries the ar-hand topic + p4."""
        envelope = _build_envelope("CUTOVER-DAY-MORGEN-CAUTION", iso_week=26)
        # Transition (prev=READY) -> fires
        payload = self.agg.build_notify_cascade_payload(
            envelope, prev_verdict="CUTOVER-DAY-MORGEN-READY"
        )
        self.assertIsNotNone(payload)
        assert payload is not None
        self.assertEqual(payload["topic"], "wakir-ar-hand")
        self.assertEqual(payload["priority"], 4)
        self.assertIn("warning", payload["tags"])
        self.assertTrue(payload["audit_only"])
        self.assertEqual(
            payload["verdict_summary"]["prev_verdict"],
            "CUTOVER-DAY-MORGEN-READY",
        )

    # ---- 11 READY suppression returns None ----------------------------------

    def test_11_ready_returns_none(self) -> None:
        """READY input never produces a payload (returns None)."""
        envelope = _build_envelope("CUTOVER-DAY-MORGEN-READY", iso_week=24)
        for prev in (None, "CUTOVER-DAY-MORGEN-CAUTION"):
            self.assertIsNone(
                self.agg.build_notify_cascade_payload(
                    envelope, prev_verdict=prev
                ),
                f"READY must yield None payload (prev={prev!r})",
            )

    # ---- 12 Stable-CAUTION suppression --------------------------------------

    def test_12_stable_caution_returns_none(self) -> None:
        """Stable CAUTION (prev=CAUTION) must NOT fire (anti-spam)."""
        envelope = _build_envelope("CUTOVER-DAY-MORGEN-CAUTION")
        self.assertIsNone(
            self.agg.build_notify_cascade_payload(
                envelope, prev_verdict="CUTOVER-DAY-MORGEN-CAUTION"
            )
        )


class Tag65CliEndToEndTests(unittest.TestCase):
    """Pin the CLI ``--emit-notify-cascade`` end-to-end behaviour."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.agg = _load_aggregator()

    def _run_cli(
        self,
        tmpdir: Path,
        *,
        engine: str,
        pyramide: str,
        e2e: str,
        prev_verdict: str | None = None,
    ) -> tuple[Path, Path]:
        """Run the aggregator CLI with --emit-notify-cascade."""
        def _write(p: Path, verdict: str) -> Path:
            p.write_text(
                json.dumps({"schema_version": 1, "verdict": verdict}),
                encoding="utf-8",
            )
            return p

        eng = _write(tmpdir / "engine.json", engine)
        pyr = _write(tmpdir / "pyramide.json", pyramide)
        e2e_p = _write(tmpdir / "e2e.json", e2e)
        out = tmpdir / "verdict.json"
        cascade = tmpdir / "cascade.json"
        argv = [
            "--engine-envelope",
            str(eng),
            "--pyramide-envelope",
            str(pyr),
            "--e2e-envelope",
            str(e2e_p),
            "--iso-week",
            "24",
            "--output",
            str(out),
            "--emit-notify-cascade",
            str(cascade),
        ]
        if prev_verdict is not None:
            argv.extend(["--prev-verdict", prev_verdict])
        rc = self.agg.main(argv)
        self.assertEqual(rc, 0)
        return out, cascade

    # ---- 13 CLI BLOCK emits non-suppressed cascade --------------------------

    def test_13_cli_block_emits_cascade(self) -> None:
        """CLI: BLOCK verdict produces a fired (non-suppressed) cascade."""
        with tempfile.TemporaryDirectory() as td:
            _, cascade_path = self._run_cli(
                Path(td),
                engine="PRE-CUTOVER-DEFECT",
                pyramide="ACCEPTANCE-PYRAMIDE-READY",
                e2e="E2E-READY",
            )
            cascade = json.loads(cascade_path.read_text(encoding="utf-8"))
            self.assertNotIn("suppressed", cascade)
            self.assertEqual(cascade["topic"], "wakir-ar-hand-critical")
            self.assertEqual(cascade["priority"], 5)
            self.assertTrue(cascade["audit_only"])

    # ---- 14 CLI READY emits suppressed-stub artifact ------------------------

    def test_14_cli_ready_emits_suppressed_stub(self) -> None:
        """CLI: READY verdict produces a suppressed-stub (deterministic file)."""
        with tempfile.TemporaryDirectory() as td:
            _, cascade_path = self._run_cli(
                Path(td),
                engine="PRE-CUTOVER-READY",
                pyramide="ACCEPTANCE-PYRAMIDE-READY",
                e2e="E2E-READY",
            )
            self.assertTrue(cascade_path.is_file())
            cascade = json.loads(cascade_path.read_text(encoding="utf-8"))
            self.assertTrue(cascade["suppressed"])
            self.assertEqual(
                cascade["suppression_reason"], "READY-verdict-no-cascade"
            )
            self.assertTrue(cascade["audit_only"])
            # No ntfy fields on a suppressed stub.
            self.assertNotIn("topic", cascade)
            self.assertNotIn("priority", cascade)

    # ---- 15 CLI stable-CAUTION suppressed ------------------------------------

    def test_15_cli_stable_caution_suppressed(self) -> None:
        """CLI: stable CAUTION (prev=CAUTION) produces a suppressed stub."""
        with tempfile.TemporaryDirectory() as td:
            _, cascade_path = self._run_cli(
                Path(td),
                engine="PRE-CUTOVER-READY",
                pyramide="ACCEPTANCE-PYRAMIDE-DRIFT",
                e2e="E2E-READY",
                prev_verdict="CUTOVER-DAY-MORGEN-CAUTION",
            )
            cascade = json.loads(cascade_path.read_text(encoding="utf-8"))
            self.assertTrue(cascade["suppressed"])
            self.assertEqual(
                cascade["suppression_reason"], "stable-CAUTION-no-cascade"
            )


class Tag65WorkflowShapeTests(unittest.TestCase):
    """Pin the workflow byte-shape invariants - audit-only stance."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    # ---- 16 Workflow file exists --------------------------------------------

    def test_16_workflow_file_exists(self) -> None:
        self.assertTrue(
            WORKFLOW_PATH.is_file(),
            f"workflow file must exist at {WORKFLOW_PATH}",
        )

    # ---- 17 Workflow audit-only stance --------------------------------------

    def test_17_workflow_audit_only_no_outbound_post(self) -> None:
        """The workflow MUST NOT POST to ntfy.sh (audit-only stance)."""
        text = self.workflow_text
        # No actual ntfy POSTs: rule out curl-POST commands referring
        # to ntfy.sh. The aggregator's operator_curl_hint string is
        # inert (it is a hint, not an executed command).
        self.assertNotIn("curl -X POST https://ntfy.sh", text)
        self.assertNotIn('curl -fsSL -X POST -H', text)
        # Audit-only marker appears in the comment block.
        self.assertIn("audit-only", text.lower())
        # The workflow declares it explicitly in step-summary text.
        self.assertIn("NO ntfy POST", text)

    # ---- 18 Workflow consumes Tag-64 scheduler ------------------------------

    def test_18_workflow_consumes_tag64_scheduler(self) -> None:
        """The workflow triggers on the Tag-64 scheduler completion."""
        text = self.workflow_text
        self.assertIn("cutover-day-morgen-auto-scheduler", text)
        self.assertIn("workflow_run:", text)
        self.assertIn("types:", text)
        self.assertIn("completed", text)

    # ---- 19 Workflow permissions read-only ----------------------------------

    def test_19_workflow_permissions_read_only(self) -> None:
        """The workflow declares contents:read + actions:read only."""
        text = self.workflow_text
        self.assertIn("contents: read", text)
        self.assertIn("actions: read", text)
        # No write permissions.
        self.assertNotIn("contents: write", text)
        self.assertNotIn("packages: write", text)
        self.assertNotIn("issues: write", text)


if __name__ == "__main__":
    unittest.main()
