#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Decision-aggregator for ``pre-cutover-final-sanity-gate.yml`` (Tomas Tag-53).

The Tag-53 final-sanity-gate is the last pre-KW-24 readiness probe
across **seven** Phase-3-Marathon substrates (vs. four for the
Tag-41 ``phase-3c-pre-cutover-sanity`` workflow). It is the union
gate that the AR-Hand-ratification step in ``phase-3-cutover-day-
auto-scheduler.yml`` consults the morning of Cutover-Day.

Seven substrates probed
-----------------------

* ``S1`` engine_manifest (Persona-Engine Manifest 0.5.2-final-pre-cutover
  + Pin-Pack parity, Selin Tag-52 PR #336 substrate).
* ``S2`` spec_freeze (Wirelang spec v0.4.3-freeze marker presence
  + frontmatter version-bump, Reza Tag-48 PR #324 substrate).
* ``S3`` sbom (15-binary CycloneDX SBOM bundle, Kai Tag-48 PR
  #311 substrate).
* ``S4`` build_reproducibility (Build-Reproducibility-Daily
  green-window probe, Noa Tag-46 substrate).
* ``S5`` cosign_oidc (Cosign-Keyless-OIDC-Drift-Probe + image-
  verify substrates, Kai Tag-47 PR #307 substrate).
* ``S6`` welle_probes (seven per-Welle pre-cutover-probe scripts
  + hot-spot probe substrates, Reza/Selin Tag-40..Tag-45
  substrate union).
* ``S7`` marathon_tracker (Selin Tag-40 PR #261 tracker substrate
  + marathon-tracker-gate workflow + tracker-state-file schema).

Decision rule
-------------

Each substrate is one of ``{green, yellow, red}``.

* ``READY``   - all seven substrates green.
* ``CAUTION`` - 1..2 substrates yellow, the rest green; zero red.
* ``BLOCK``   - any substrate red, OR three or more yellow.

The threshold ``yellows>=3 -> BLOCK`` is tighter than the four-
substrate Tag-41 gate (which uses ``yellows>=2 -> BLOCK``). Seven
substrates carry more redundancy; up to two yellow signals can
plausibly clear with a CAUTION-path operator-hand workaround,
three indicate the marathon-substrate-set has degraded enough to
warrant BLOCK.

Empty / missing env-vars default to ``red`` (we assume an upstream
job failed entirely if its output is absent).

Exit code
---------

Always ``0``. The verdict-envelope's ``verdict`` field carries
the BLOCK/CAUTION/READY signal; the calling workflow translates
that to step-exit semantics.

Hermetic
--------

stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


VALID_STATUSES = ("green", "yellow", "red")

# Canonical substrate-keys in documented order. The workflow YAML
# emits ``S<n>_STATUS`` env-vars in this same order; keeping the
# tuple here as the single source of truth lets the test-suite
# enumerate them without duplicating the list.
SUBSTRATES = (
    "engine_manifest",
    "spec_freeze",
    "sbom",
    "build_reproducibility",
    "cosign_oidc",
    "welle_probes",
    "marathon_tracker",
)

# Operator-playbook cross-substrate links, recorded on the verdict
# envelope so an artifact-only consumer (the auto-scheduler) does
# not have to re-resolve where to look.
CROSS_SUBSTRATE_LINKS = {
    "engine_manifest_pin_pack": "infra/persona-engine/pin-pack-0.5.2-final-pre-cutover.yaml",
    "engine_manifest_doc": "wirelang/persona_engine/MANIFEST-0.5.2-final-pre-cutover.md",
    "spec_freeze_doc": "wirelang/specs/wirelang-spec-v0-4-3.md",
    "sbom_workflow": ".github/workflows/15-binary-sbom-daily.yml",
    "build_reproducibility_workflow": ".github/workflows/build-reproducibility-daily.yml",
    "cosign_oidc_workflow": ".github/workflows/cosign-keyless-oidc-drift-probe.yml",
    "welle_probes_dir": "scripts/phase-3c/",
    "marathon_tracker_script": "scripts/phase-3c/marathon-aggregat-tracker.py",
    "marathon_tracker_workflow": ".github/workflows/phase-3c-marathon-tracker-gate.yml",
    "tag_41_sanity_workflow": ".github/workflows/phase-3c-pre-cutover-sanity.yml",
    "auto_scheduler_workflow": ".github/workflows/phase-3-cutover-day-auto-scheduler.yml",
}


def _normalise(raw: str | None) -> str:
    """Coerce an env-var value to a known status. Empty -> red."""
    if raw is None:
        return "red"
    v = raw.strip().lower()
    if v in VALID_STATUSES:
        return v
    if v == "":
        return "red"
    # Unknown values are treated as red (loud failure mode).
    return "red"


def decide(steps: Mapping[str, str]) -> str:
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    if reds >= 1:
        return "BLOCK"
    if yellows >= 3:
        return "BLOCK"
    if 1 <= yellows <= 2:
        return "CAUTION"
    if greens == len(steps):
        return "READY"
    return "BLOCK"


def _env_key(substrate: str) -> str:
    """Map ``engine_manifest`` -> ``S1_STATUS`` (1-indexed by position)."""
    idx = SUBSTRATES.index(substrate) + 1
    return f"S{idx}_STATUS"


def build_envelope(env: Mapping[str, str]) -> dict:
    steps = {
        substrate: _normalise(env.get(_env_key(substrate)))
        for substrate in SUBSTRATES
    }
    reds = sum(1 for v in steps.values() if v == "red")
    yellows = sum(1 for v in steps.values() if v == "yellow")
    greens = sum(1 for v in steps.values() if v == "green")
    verdict = decide(steps)
    failed = [k for k, v in steps.items() if v != "green"]
    notes_raw = env.get("SUBSTRATE_NOTES", "") or ""
    # SUBSTRATE_NOTES is a `;`-separated list of `<substrate>:<note>`
    # records produced by the per-step probes. We keep the raw split;
    # consumers (auto-scheduler, AR-Hand summary) read the records by
    # substrate-key prefix.
    substrate_notes = [n for n in notes_raw.split(";") if n]
    return {
        "schema_version": 1,
        "workflow": "pre-cutover-final-sanity-gate",
        "tag": "tag-53",
        "emitted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "github_run_id": env.get("GITHUB_RUN_ID"),
        "github_sha": env.get("GITHUB_SHA"),
        "github_ref": env.get("GITHUB_REF"),
        "verdict": verdict,
        "step_results": steps,
        "failed_steps": failed,
        "substrate_notes": substrate_notes,
        "counts": {"green": greens, "yellow": yellows, "red": reds},
        "decision_rule": {
            "ready": "all seven substrates green",
            "caution": "1..2 yellow, zero red",
            "block": "any red OR three or more yellow",
        },
        "cross_substrate_links": CROSS_SUBSTRATE_LINKS,
    }


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(
        description="Aggregate per-substrate pre-cutover-final-sanity-gate results."
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the verdict-envelope JSON.",
    )
    p.add_argument(
        "--print-stdout",
        action="store_true",
        help="Also print the envelope to stdout.",
    )
    args = p.parse_args(argv[1:])

    envelope = build_envelope(os.environ)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if args.print_stdout:
        print(json.dumps(envelope, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
