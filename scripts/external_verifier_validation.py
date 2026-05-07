#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""External-verifier cross-tool parity validator for wakir-wat-manifest-v1.

Loads the formal JSON-Schema (``wirelang/schemas/wakir-wat-manifest-v1.json``)
and a shared test-vector file, then runs every vector through:

1. The Python ``jsonschema`` Draft-2020-12 reference validator.
2. The Node.js ``ajv`` validator under
   ``tooling/external-verifier-ajv/`` (shells out to ``node validate.js``
   with the same vectors file; the Node.js side prints a JSON report).

Cross-tool parity is the contract: each vector's verdict (accept /
reject) must agree across both validators *and* must equal the
``expect`` field declared in the vector. Any drift is a schema-
correctness bug, not an implementation peculiarity.

This script exists for two purposes:

- **Manual smoke** by external implementers ("does my validator agree
  with the reference set?"). Drop a third validator into the same
  vectors file, compare verdicts, and the schema-correctness
  conversation has objective ground truth.
- **CI gate** (off-default for now; opt-in per Sprint-3 follow-up
  Open-Item). Once the Node.js side is wired into a CI step the script
  exits non-zero on any mismatch.

Exit codes:

  0  Every vector matched its expected verdict in *every* configured
     validator.
  1  At least one vector mismatched (schema-side bug).
  2  CLI / file-loading / Node.js-availability error (cannot draw
     conclusions; rerun with ``--require-node`` or fix environment).

Usage:

  python scripts/external_verifier_validation.py
  python scripts/external_verifier_validation.py --node-only
  python scripts/external_verifier_validation.py --python-only
  python scripts/external_verifier_validation.py --vectors path/to/file.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "wirelang" / "schemas" / "wakir-wat-manifest-v1.json"
AJV_TOOL_DIR = REPO_ROOT / "tooling" / "external-verifier-ajv"
DEFAULT_VECTORS = AJV_TOOL_DIR / "test-vectors.json"

#: Real-manifest fixture cohort used by ``--real-tv2``. Each entry is
#: an hour-receipt directory carrying ``manifest.json`` + ``root.bin``
#: + ``root.bin.ots``. The four hours together form the TV-2
#: Bitcoin-anchored multi-hour reference run committed to the repo
#: in Sprint-3 Tag-2.
TV2_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "wat-tv2-real"
TV2_HOUR_SLOTS: tuple[str, ...] = (
    "2026-05-27T00",
    "2026-05-27T01",
    "2026-05-27T02",
    "2026-05-27T03",
)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def run_python_validator(schema: dict, vectors: list[dict]) -> dict:
    """Validate every vector with Python ``jsonschema`` Draft-2020-12.

    Returns a report dict matching the Node.js side's shape so the
    parity comparison is symmetric.
    """
    try:
        from jsonschema import Draft202012Validator
    except ImportError as e:  # pragma: no cover (env-side)
        raise SystemExit(
            f"jsonschema not installed: {e}. Install via "
            "`pip install jsonschema>=4`."
        )

    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)

    report = {
        "tool": "python-jsonschema",
        "schema_id": schema.get("$id"),
        "total": len(vectors),
        "matched": 0,
        "mismatched": 0,
        "results": [],
    }

    for v in vectors:
        name = v.get("name", "<unnamed>")
        expect = v.get("expect")
        manifest = v.get("manifest")

        if expect not in ("accept", "reject"):
            raise SystemExit(
                f'vector "{name}": expect must be "accept" or "reject"'
            )

        errors = list(validator.iter_errors(manifest))
        verdict = "accept" if not errors else "reject"
        matched = verdict == expect

        if matched:
            report["matched"] += 1
        else:
            report["mismatched"] += 1

        report["results"].append(
            {
                "name": name,
                "expect": expect,
                "verdict": verdict,
                "matched": matched,
                "errors": [
                    {
                        "instancePath": "/" + "/".join(str(p) for p in e.absolute_path),
                        "keyword": e.validator,
                        "message": e.message,
                    }
                    for e in errors
                ],
            }
        )

    return report


def run_node_validator(vectors_path: Path) -> dict | None:
    """Shell out to ``node tooling/external-verifier-ajv/validate.js``.

    Returns ``None`` if Node is unavailable or ``node_modules`` missing.
    Returns the parsed JSON report otherwise.
    """
    node_bin = shutil.which("node")
    if node_bin is None:
        return None

    if not (AJV_TOOL_DIR / "node_modules").exists():
        return None

    cmd = [
        node_bin,
        str(AJV_TOOL_DIR / "validate.js"),
        f"--schema={SCHEMA_PATH}",
        f"--vectors={vectors_path}",
    ]
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(AJV_TOOL_DIR),
        check=False,
    )
    # Exit 0 (all matched) and exit 1 (mismatch) both produce a valid
    # report. Exit 2 means CLI / file-loading problem and we surface it
    # as a hard fail rather than try to parse a corrupt stdout.
    if proc.returncode == 2:
        raise SystemExit(
            f"node validator hard-failed (rc=2): stderr={proc.stderr!r}"
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"node validator stdout is not JSON: {e}; stdout={proc.stdout!r}"
        )


# ---------------------------------------------------------------------------
# Parity check
# ---------------------------------------------------------------------------


def compare_reports(py: dict, node: dict | None) -> tuple[bool, list[str]]:
    """Return ``(parity_ok, diffs)``.

    parity_ok is ``True`` when every vector has the same verdict on
    both sides. ``diffs`` lists human-readable lines describing the
    differences.
    """
    diffs: list[str] = []
    if node is None:
        return True, ["node side skipped (validator unavailable)"]

    by_name_py = {r["name"]: r for r in py["results"]}
    by_name_node = {r["name"]: r for r in node["results"]}

    all_names = sorted(set(by_name_py) | set(by_name_node))
    parity_ok = True
    for name in all_names:
        if name not in by_name_py:
            parity_ok = False
            diffs.append(f"{name}: missing in python report")
            continue
        if name not in by_name_node:
            parity_ok = False
            diffs.append(f"{name}: missing in node report")
            continue
        py_v = by_name_py[name]["verdict"]
        node_v = by_name_node[name]["verdict"]
        if py_v != node_v:
            parity_ok = False
            diffs.append(
                f"{name}: python={py_v} node={node_v} (parity violation)"
            )

    return parity_ok, diffs


# ---------------------------------------------------------------------------
# Real-TV-2 mode
# ---------------------------------------------------------------------------


def load_tv2_real_vectors() -> list[dict]:
    """Load the four TV-2 real-manifest hour-receipts as accept-vectors.

    The vectors carry ``expect="accept"`` and a ``manifest`` field
    matching the on-disk JSON; the ajv side feeds them through the
    same v1-schema validator that exercises the synthetic test-set.
    """
    vectors: list[dict] = []
    for slot in TV2_HOUR_SLOTS:
        manifest_path = TV2_FIXTURE_ROOT / slot / "manifest.json"
        if not manifest_path.exists():
            raise SystemExit(
                f"TV-2 real-manifest fixture missing: {manifest_path}. "
                "Run from a repo with the wat-tv2-real fixtures committed."
            )
        with manifest_path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        vectors.append(
            {
                "name": f"tv2-real-{slot}",
                "expect": "accept",
                "manifest": manifest,
            }
        )
    return vectors


def run_real_manifest_pipeline(
    *, check_ots_anchor: bool = True, use_schema_file: bool = True
) -> dict:
    """Run ``verify_real_manifest_file`` against each TV-2 hour.

    Returns a report dict in the same shape as the schema-side reports
    so the entry-point can render parity output uniformly.
    """
    from wat.verify.manifest_v2 import verify_real_manifest_file

    report = {
        "tool": "wat.verify.manifest_v2.verify_real_manifest_file",
        "schema_id": None,
        "total": len(TV2_HOUR_SLOTS),
        "matched": 0,
        "mismatched": 0,
        "results": [],
    }
    for slot in TV2_HOUR_SLOTS:
        manifest_path = TV2_FIXTURE_ROOT / slot / "manifest.json"
        result = verify_real_manifest_file(
            manifest_path,
            check_ots_anchor=check_ots_anchor,
            use_schema_file=use_schema_file,
        )
        verdict = "accept" if result.ok else "reject"
        matched = result.ok  # expect-accept on production hour-receipts
        if matched:
            report["matched"] += 1
        else:
            report["mismatched"] += 1
        report["results"].append(
            {
                "name": f"tv2-real-{slot}",
                "expect": "accept",
                "verdict": verdict,
                "matched": matched,
                "fields_ok": result.fields_ok,
                "integrity_ok": result.integrity_ok,
                "ots_anchor_ok": result.ots_anchor.ok,
                "failure_reason": result.failure_reason,
                "version": result.version,
            }
        )
    return report


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--vectors",
        type=Path,
        default=DEFAULT_VECTORS,
        help=f"path to test-vectors JSON file (default: {DEFAULT_VECTORS})",
    )
    parser.add_argument(
        "--python-only",
        action="store_true",
        help="skip the Node.js / ajv side",
    )
    parser.add_argument(
        "--node-only",
        action="store_true",
        help="skip the Python jsonschema side",
    )
    parser.add_argument(
        "--require-node",
        action="store_true",
        help="hard-fail if node is unavailable instead of skipping",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the per-vector verdict table",
    )
    parser.add_argument(
        "--real-tv2",
        action="store_true",
        help=(
            "live-run the TV-2 real-manifest fixture cohort "
            "(tests/fixtures/wat-tv2-real/) through both the schema-file "
            "validators AND the verify_real_manifest_file pipeline; "
            "all four hour-receipts must accept on every configured side"
        ),
    )
    args = parser.parse_args(argv)

    if args.python_only and args.node_only:
        print("--python-only and --node-only are mutually exclusive", file=sys.stderr)
        return 2

    if not SCHEMA_PATH.exists():
        print(f"schema file not found: {SCHEMA_PATH}", file=sys.stderr)
        return 2

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    if args.real_tv2:
        # In --real-tv2 mode the vectors source is the on-disk fixture
        # cohort; the synthetic vectors file is not consulted. The
        # real-manifest pipeline runs in addition to the schema-file
        # validators so we cover both code paths against the same
        # production manifests.
        vectors = load_tv2_real_vectors()
        # Persist the wrapped vectors to a tmp-file so the Node.js
        # side can read them; the synthetic test-vectors.json shape
        # is identical so no driver-side changes are needed.
        import tempfile

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", prefix="tv2-real-vectors-", delete=False
        )
        json.dump(vectors, tmp)
        tmp.close()
        vectors_path = Path(tmp.name)
    else:
        if not args.vectors.exists():
            print(f"vectors file not found: {args.vectors}", file=sys.stderr)
            return 2
        vectors = json.loads(args.vectors.read_text(encoding="utf-8"))
        vectors_path = args.vectors

    if not isinstance(vectors, list):
        print("vectors file must contain a JSON array", file=sys.stderr)
        return 2

    py_report: dict[str, Any] | None = None
    node_report: dict[str, Any] | None = None

    if not args.node_only:
        py_report = run_python_validator(schema, vectors)
    if not args.python_only:
        node_report = run_node_validator(vectors_path)
        if node_report is None and args.require_node:
            print(
                "node validator unavailable (no `node` on PATH or "
                "node_modules missing); rerun without --require-node "
                "or `cd tooling/external-verifier-ajv && npm install`",
                file=sys.stderr,
            )
            return 2

    real_pipeline_report: dict[str, Any] | None = None
    if args.real_tv2:
        real_pipeline_report = run_real_manifest_pipeline(
            check_ots_anchor=True, use_schema_file=True
        )

    # Render
    if not args.quiet:
        if py_report is not None:
            _render_report("python (jsonschema)", py_report)
        if node_report is not None:
            _render_report("node (ajv)", node_report)
        elif not args.python_only:
            print("node side: SKIPPED (validator unavailable)")
        if real_pipeline_report is not None:
            _render_report(
                "wat.verify.manifest_v2.verify_real_manifest_file",
                real_pipeline_report,
            )

    # Verdict
    fail = False
    if py_report and py_report["mismatched"] > 0:
        fail = True
        print(
            f"python validator: {py_report['mismatched']} of "
            f"{py_report['total']} vectors mismatched expected verdict",
            file=sys.stderr,
        )
    if node_report and node_report["mismatched"] > 0:
        fail = True
        print(
            f"node validator: {node_report['mismatched']} of "
            f"{node_report['total']} vectors mismatched expected verdict",
            file=sys.stderr,
        )

    if py_report is not None and node_report is not None:
        parity_ok, diffs = compare_reports(py_report, node_report)
        if not parity_ok:
            fail = True
            print("CROSS-TOOL PARITY VIOLATION:", file=sys.stderr)
            for d in diffs:
                print(f"  {d}", file=sys.stderr)
        else:
            label = (
                "real-tv2 cross-tool"
                if args.real_tv2
                else "cross-tool"
            )
            print(
                f"{label} parity OK ({py_report['total']} vectors, "
                "verdicts agree)"
            )

    if real_pipeline_report is not None:
        if real_pipeline_report["mismatched"] > 0:
            fail = True
            print(
                f"verify_real_manifest_file: "
                f"{real_pipeline_report['mismatched']} of "
                f"{real_pipeline_report['total']} hour-receipts failed",
                file=sys.stderr,
            )
            for r in real_pipeline_report["results"]:
                if not r["matched"]:
                    print(
                        f"  {r['name']}: fields={r['fields_ok']} "
                        f"integrity={r['integrity_ok']} "
                        f"ots={r['ots_anchor_ok']} "
                        f"reason={r['failure_reason']!r}",
                        file=sys.stderr,
                    )
        else:
            print(
                f"verify_real_manifest_file pipeline OK "
                f"({real_pipeline_report['total']} hour-receipts, all green)"
            )

    return 1 if fail else 0


def _render_report(label: str, report: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"  schema $id: {report.get('schema_id')}")
    print(
        f"  total={report['total']} matched={report['matched']} "
        f"mismatched={report['mismatched']}"
    )
    for r in report["results"]:
        flag = "OK" if r["matched"] else "MISMATCH"
        print(
            f"  [{flag}] {r['name']:<45s} expect={r['expect']:<6s} "
            f"verdict={r['verdict']}"
        )


if __name__ == "__main__":
    sys.exit(main())
