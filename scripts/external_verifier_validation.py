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
3. The Python ``fastjsonschema`` validator (Phase-2 Sprint-6 Tag-1).
   A second independent Python-side implementation that compiles the
   schema to native Python code. Triangulating against ``jsonschema``
   catches bugs in either library's Draft-2020-12 implementation that
   would otherwise be invisible behind a single-implementation pin.

Cross-tool parity is the contract: each vector's verdict (accept /
reject) must agree across every configured validator *and* must equal
the ``expect`` field declared in the vector. Any drift is a schema-
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
  python scripts/external_verifier_validation.py --skip-fastjsonschema
  python scripts/external_verifier_validation.py --require-fastjsonschema
  python scripts/external_verifier_validation.py --real-tv2
  python scripts/external_verifier_validation.py --real-tv2 --verify-signature
  python scripts/external_verifier_validation.py --real-tv2 --verify-signature --verify-signature-strict
  python scripts/external_verifier_validation.py --real-tv3 --verify-signature
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

#: Module-level holder list keeping :class:`tempfile.TemporaryDirectory`
#: handles alive across the duration of :func:`main`. Without this the
#: staged-signed-cohort directory would be reaped before the verifier
#: pipeline reads it (the TemporaryDirectory context manager would fire
#: at the assignment site). This is the cheapest deterministic-lifetime
#: pattern that survives a CLI entrypoint without a context-manager
#: wrapper.
_signed_tmp_holder: list[Any] = []

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

#: Real-manifest fixture cohort used by ``--real-tv3``. Single-hour
#: TV-3 close-out run (Sprint-3 Tag-3 commit). Same triple shape as
#: TV-2; reuses the same code paths via the generic
#: ``run_real_manifest_pipeline_for`` helper.
TV3_FIXTURE_ROOT = REPO_ROOT / "tests" / "fixtures" / "wat-tv3-real"
TV3_HOUR_SLOTS: tuple[str, ...] = ("2026-05-26T17",)


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


def run_fastjsonschema_validator(schema: dict, vectors: list[dict]) -> dict | None:
    """Validate every vector with Python ``fastjsonschema``.

    Returns ``None`` if ``fastjsonschema`` is not installed (treated
    like the Node.js skip path). Returns a report dict matching the
    other validators' shape when available.

    ``fastjsonschema`` compiles the schema to native Python code and is
    a completely separate implementation from ``jsonschema``; this is
    the third pole that makes cross-tool parity a genuine triangulation
    rather than a one-library pin.
    """
    try:
        import fastjsonschema
    except ImportError:
        return None

    # fastjsonschema does not have a Draft-2020-12-specific compile flag
    # at the API level; it dispatches by ``$schema``. Our schema already
    # carries ``"$schema": "https://json-schema.org/draft/2020-12/schema"``
    # so the compile path picks Draft-2020-12 automatically.
    try:
        validate = fastjsonschema.compile(schema)
    except Exception as e:  # pragma: no cover (schema-side)
        raise SystemExit(f"fastjsonschema compile failure: {e}")

    report = {
        "tool": "python-fastjsonschema",
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

        try:
            validate(manifest)
            verdict = "accept"
            errors: list[dict] = []
        except fastjsonschema.JsonSchemaException as e:
            verdict = "reject"
            errors = [
                {
                    "instancePath": "/" + "/".join(
                        str(p) for p in getattr(e, "path", []) or []
                    ),
                    "keyword": getattr(e, "rule", "<unknown>"),
                    "message": e.message,
                }
            ]
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
                "errors": errors,
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
    """Return ``(parity_ok, diffs)`` for python-vs-node parity.

    parity_ok is ``True`` when every vector has the same verdict on
    both sides. ``diffs`` lists human-readable lines describing the
    differences. Kept for backward-compat with the original two-way
    parity-API; use :func:`compare_reports_multi` for the N-way path.
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


def compare_reports_multi(reports: list[dict]) -> tuple[bool, list[str]]:
    """Return ``(parity_ok, diffs)`` for N-way validator parity.

    Each report dict must carry a ``tool`` label (used to identify the
    validator in diff messages) and a ``results`` list with per-vector
    verdicts. parity_ok is True when every vector that appears in *any*
    report yields the same verdict in *every* report it appears in.

    Reports may be a subset (e.g. node skipped because Node.js absent);
    only the validators that did run participate in the comparison.
    """
    diffs: list[str] = []
    reports = [r for r in reports if r is not None]
    if len(reports) < 2:
        return True, [
            "fewer than 2 validators ran; parity not assessed"
        ]

    all_names: set[str] = set()
    for r in reports:
        all_names.update(x["name"] for x in r["results"])

    parity_ok = True
    for name in sorted(all_names):
        verdicts: dict[str, str] = {}
        for r in reports:
            for x in r["results"]:
                if x["name"] == name:
                    verdicts[r["tool"]] = x["verdict"]
                    break
            else:
                verdicts[r["tool"]] = "<missing>"

        unique = set(verdicts.values()) - {"<missing>"}
        if len(unique) > 1:
            parity_ok = False
            rendered = " ".join(
                f"{tool}={v}" for tool, v in sorted(verdicts.items())
            )
            diffs.append(f"{name}: {rendered} (parity violation)")
        elif "<missing>" in verdicts.values():
            missing_tools = [
                tool for tool, v in verdicts.items() if v == "<missing>"
            ]
            parity_ok = False
            diffs.append(
                f"{name}: missing in reports from {missing_tools}"
            )

    return parity_ok, diffs


# ---------------------------------------------------------------------------
# Real-TV-2 mode
# ---------------------------------------------------------------------------


def load_real_vectors_for(
    fixture_root: Path, hour_slots: tuple[str, ...], tag: str
) -> list[dict]:
    """Generic real-manifest cohort loader.

    ``tag`` is the cohort label (e.g. ``"tv2"``, ``"tv3"``) used to
    name the vectors in driver output. Each loaded hour-receipt
    becomes an accept-vector matching the synthetic test-vectors
    shape so the Node.js ajv side ingests them through the same code
    path.
    """
    vectors: list[dict] = []
    for slot in hour_slots:
        manifest_path = fixture_root / slot / "manifest.json"
        if not manifest_path.exists():
            raise SystemExit(
                f"{tag.upper()} real-manifest fixture missing: "
                f"{manifest_path}. Run from a repo with the "
                f"wat-{tag}-real fixtures committed."
            )
        with manifest_path.open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        vectors.append(
            {
                "name": f"{tag}-real-{slot}",
                "expect": "accept",
                "manifest": manifest,
            }
        )
    return vectors


def load_tv2_real_vectors() -> list[dict]:
    """Backward-compat wrapper for TV-2 cohort (Sprint-3 Tag-2 surface)."""
    return load_real_vectors_for(TV2_FIXTURE_ROOT, TV2_HOUR_SLOTS, "tv2")


def load_tv3_real_vectors() -> list[dict]:
    """Load TV-3 single-hour real-manifest receipt as accept-vector."""
    return load_real_vectors_for(TV3_FIXTURE_ROOT, TV3_HOUR_SLOTS, "tv3")


def stage_signed_cohort(
    fixture_root: Path,
    hour_slots: tuple[str, ...],
    *,
    out_root: Path,
    kid: str = "kid-real-tv-driver",
) -> tuple[Path, bytes, bytes]:
    """Stage signed deep-copies of every hour-slot manifest under ``out_root``.

    The production aggregator (``wat/cmd/aggregator_cli.py`` v1) does
    NOT emit signed manifests today (Sprint-5 Tag-5 open-item). To run
    the full ``verify_real_manifest_file(verify_signature=True, ...)``
    path against the on-disk TV-2 cohort the driver hand-signs in-
    memory deep-copies of each manifest and writes them to a temporary
    directory next to byte-for-byte copies of the ``root.bin`` /
    ``root.bin.ots`` side-files. The repository fixtures are NOT
    mutated.

    Pattern lifted from
    ``tests/wat/test_tv2_real_manifest_sig_verify.py::_stage_signed_hour``;
    the test and the driver share this code path through this helper
    (Sprint-6 Tag-2 deduplication: the driver was assembled from the
    same recipe the test had already validated).

    Returns ``(staged_cohort_root, private_seed_bytes, public_key_bytes)``
    so callers can pass the public key into the verifier and (in
    negative-path drivers) the private seed back for additional
    manipulations.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from wat.identity.manifest_signing import SIGNATURE_FIELD, sign_manifest

    priv = Ed25519PrivateKey.generate()
    private_seed = priv.private_bytes_raw()
    public_key = priv.public_key().public_bytes_raw()

    for slot in hour_slots:
        src_dir = fixture_root / slot
        dst_dir = out_root / slot
        dst_dir.mkdir(parents=True, exist_ok=True)

        with (src_dir / "manifest.json").open("r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        signed = sign_manifest(manifest, private_seed, kid=kid)
        signed_manifest = dict(signed.manifest)
        signed_manifest[SIGNATURE_FIELD] = signed.signature

        (dst_dir / "manifest.json").write_text(
            json.dumps(signed_manifest, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        # Byte-for-byte side-file copy so the OTS-anchor check passes
        # against the same root.bin bytes the original receipt anchored.
        (dst_dir / "root.bin").write_bytes((src_dir / "root.bin").read_bytes())
        (dst_dir / "root.bin.ots").write_bytes(
            (src_dir / "root.bin.ots").read_bytes()
        )
    return out_root, private_seed, public_key


def run_real_manifest_pipeline_for(
    fixture_root: Path,
    hour_slots: tuple[str, ...],
    tag: str,
    *,
    check_ots_anchor: bool = True,
    use_schema_file: bool = True,
    verify_signature: bool = False,
    verify_signature_public_key: bytes | None = None,
    verify_signature_strict: bool = False,
) -> dict:
    """Generic ``verify_real_manifest_file`` runner over a cohort.

    Returns a report dict in the same shape as the schema-side reports
    so the entry-point can render parity output uniformly.

    When ``verify_signature=True`` the caller is responsible for staging
    a signed copy of the cohort (see :func:`stage_signed_cohort`) and
    pointing ``fixture_root`` at that staged copy. The signature-status
    of each hour is included in the per-result dict under
    ``signature_status``.
    """
    from wat.verify.manifest_v2 import VerifyMode, verify_real_manifest_file

    tool_label = "wat.verify.manifest_v2.verify_real_manifest_file"
    if verify_signature:
        # Surface the signature-mode in the tool label so the rendered
        # report is unambiguous about which gate ran.
        mode_label = "strict" if verify_signature_strict else "permissive"
        tool_label = f"{tool_label} (sig:{mode_label})"

    report = {
        "tool": tool_label,
        "schema_id": None,
        "total": len(hour_slots),
        "matched": 0,
        "mismatched": 0,
        "results": [],
    }
    sig_mode = (
        VerifyMode.STRICT
        if verify_signature_strict
        else VerifyMode.PERMISSIVE
    )
    for slot in hour_slots:
        manifest_path = fixture_root / slot / "manifest.json"
        result = verify_real_manifest_file(
            manifest_path,
            check_ots_anchor=check_ots_anchor,
            use_schema_file=use_schema_file,
            verify_signature=verify_signature,
            verify_signature_public_key=verify_signature_public_key,
            verify_signature_mode=sig_mode,
        )
        verdict = "accept" if result.ok else "reject"
        matched = result.ok  # expect-accept on production hour-receipts
        if matched:
            report["matched"] += 1
        else:
            report["mismatched"] += 1
        report["results"].append(
            {
                "name": f"{tag}-real-{slot}",
                "expect": "accept",
                "verdict": verdict,
                "matched": matched,
                "fields_ok": result.fields_ok,
                "integrity_ok": result.integrity_ok,
                "ots_anchor_ok": result.ots_anchor.ok,
                "signature_status": result.signature_status,
                "failure_reason": result.failure_reason,
                "version": result.version,
            }
        )
    return report


def run_real_manifest_pipeline(
    *, check_ots_anchor: bool = True, use_schema_file: bool = True
) -> dict:
    """Backward-compat wrapper for TV-2 cohort (Sprint-3 Tag-2 surface)."""
    return run_real_manifest_pipeline_for(
        TV2_FIXTURE_ROOT,
        TV2_HOUR_SLOTS,
        "tv2",
        check_ots_anchor=check_ots_anchor,
        use_schema_file=use_schema_file,
    )


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
        "--skip-fastjsonschema",
        action="store_true",
        help=(
            "skip the Python fastjsonschema third-pole validator "
            "(default: run if fastjsonschema is importable)"
        ),
    )
    parser.add_argument(
        "--require-fastjsonschema",
        action="store_true",
        help=(
            "hard-fail if fastjsonschema is not importable instead of "
            "skipping silently"
        ),
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
    parser.add_argument(
        "--real-tv3",
        action="store_true",
        help=(
            "live-run the TV-3 real-manifest fixture cohort "
            "(tests/fixtures/wat-tv3-real/) through both the schema-file "
            "validators AND the verify_real_manifest_file pipeline; "
            "the single hour-receipt must accept on every configured side"
        ),
    )
    parser.add_argument(
        "--verify-signature",
        action="store_true",
        help=(
            "In --real-tv2 / --real-tv3 mode, ALSO run the "
            "verify_real_manifest_file pipeline with verify_signature=True "
            "against a tmp-dir signed copy of the cohort. The production "
            "aggregator does not emit signed manifests today (Sprint-5 "
            "Tag-5 open-item), so this driver hand-signs in-memory deep-"
            "copies of every hour-receipt with a fresh ephemeral Ed25519 "
            "keypair, writes the signed manifests to a tmp directory "
            "next to byte-for-byte copies of root.bin + root.bin.ots, "
            "and runs verify_real_manifest_file against the signed copy. "
            "Each hour-receipt's signature_status is reported alongside "
            "the existing fields/integrity/ots-anchor gates. The "
            "schema-file parity validators (python-jsonschema, ajv, "
            "fastjsonschema) consume the ORIGINAL unsigned cohort because "
            "the signature slot is additive and the schema-file path "
            "accepts both shapes -- the parity contract is preserved. "
            "Sprint-6 Tag-2 wire-up; unblocks the Sprint-5 Tag-5 "
            "real-manifest signature driver-mode follow-up."
        ),
    )
    parser.add_argument(
        "--verify-signature-strict",
        action="store_true",
        help=(
            "When --verify-signature is set, run the signature pipeline "
            "in VerifyMode.STRICT (reject unsigned manifests). Default "
            "(without this flag) is VerifyMode.PERMISSIVE. In normal "
            "--real-tvN --verify-signature usage the cohort has been "
            "freshly hand-signed by stage_signed_cohort(), so strict and "
            "permissive both accept; the flag exists for symmetry with "
            "the wakir-verify-manifest-v2 CLI and to make follow-up "
            "negative-path drivers explicit."
        ),
    )
    args = parser.parse_args(argv)

    if args.python_only and args.node_only:
        print("--python-only and --node-only are mutually exclusive", file=sys.stderr)
        return 2

    if args.real_tv2 and args.real_tv3:
        print(
            "--real-tv2 and --real-tv3 are mutually exclusive "
            "(re-run the script per cohort)",
            file=sys.stderr,
        )
        return 2

    if args.verify_signature and not (args.real_tv2 or args.real_tv3):
        print(
            "--verify-signature requires --real-tv2 or --real-tv3 "
            "(synthetic vector mode does not yet stage signed copies)",
            file=sys.stderr,
        )
        return 2

    if args.verify_signature_strict and not args.verify_signature:
        print(
            "--verify-signature-strict requires --verify-signature",
            file=sys.stderr,
        )
        return 2

    if not SCHEMA_PATH.exists():
        print(f"schema file not found: {SCHEMA_PATH}", file=sys.stderr)
        return 2

    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    cohort_tag: str | None = None
    cohort_fixture_root: Path | None = None
    cohort_hour_slots: tuple[str, ...] | None = None
    if args.real_tv2:
        cohort_tag = "tv2"
        cohort_fixture_root = TV2_FIXTURE_ROOT
        cohort_hour_slots = TV2_HOUR_SLOTS
    elif args.real_tv3:
        cohort_tag = "tv3"
        cohort_fixture_root = TV3_FIXTURE_ROOT
        cohort_hour_slots = TV3_HOUR_SLOTS

    if cohort_tag is not None:
        # In --real-tvN mode the vectors source is the on-disk fixture
        # cohort; the synthetic vectors file is not consulted. The
        # real-manifest pipeline runs in addition to the schema-file
        # validators so we cover both code paths against the same
        # production manifests.
        assert cohort_fixture_root is not None
        assert cohort_hour_slots is not None
        vectors = load_real_vectors_for(
            cohort_fixture_root, cohort_hour_slots, cohort_tag
        )
        # Persist the wrapped vectors to a tmp-file so the Node.js
        # side can read them; the synthetic test-vectors.json shape
        # is identical so no driver-side changes are needed.
        import tempfile

        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            prefix=f"{cohort_tag}-real-vectors-",
            delete=False,
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
    fjs_report: dict[str, Any] | None = None

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

    # fastjsonschema third-pole. Default-on (skipped only when missing
    # from the environment or when --skip-fastjsonschema is passed). The
    # --node-only mode also skips it because that mode explicitly asks
    # to run only the Node.js side.
    if not args.node_only and not args.skip_fastjsonschema:
        fjs_report = run_fastjsonschema_validator(schema, vectors)
        if fjs_report is None and args.require_fastjsonschema:
            print(
                "fastjsonschema validator unavailable (library not "
                "importable); rerun without --require-fastjsonschema "
                "or `pip install fastjsonschema`",
                file=sys.stderr,
            )
            return 2

    real_pipeline_report: dict[str, Any] | None = None
    signed_pipeline_report: dict[str, Any] | None = None
    if cohort_tag is not None:
        assert cohort_fixture_root is not None
        assert cohort_hour_slots is not None
        real_pipeline_report = run_real_manifest_pipeline_for(
            cohort_fixture_root,
            cohort_hour_slots,
            cohort_tag,
            check_ots_anchor=True,
            use_schema_file=True,
        )

        if args.verify_signature:
            # Stage hand-signed deep-copies of the cohort to a tmp
            # directory, then run the verifier pipeline a second time
            # with verify_signature=True against the staged copy. The
            # tmp dir is cleaned up at process exit via TemporaryDirectory.
            import tempfile as _tempfile

            sig_tmp = _tempfile.TemporaryDirectory(
                prefix=f"{cohort_tag}-real-signed-cohort-"
            )
            # Hold the handle for the duration of main() so the tmp
            # directory survives until after the verifier run.
            _signed_tmp_holder.append(sig_tmp)
            staged_root, _priv, pub_key = stage_signed_cohort(
                cohort_fixture_root,
                cohort_hour_slots,
                out_root=Path(sig_tmp.name),
            )
            signed_pipeline_report = run_real_manifest_pipeline_for(
                staged_root,
                cohort_hour_slots,
                cohort_tag,
                check_ots_anchor=True,
                use_schema_file=True,
                verify_signature=True,
                verify_signature_public_key=pub_key,
                verify_signature_strict=args.verify_signature_strict,
            )

    # Render
    if not args.quiet:
        if py_report is not None:
            _render_report("python (jsonschema)", py_report)
        if node_report is not None:
            _render_report("node (ajv)", node_report)
        elif not args.python_only:
            print("node side: SKIPPED (validator unavailable)")
        if fjs_report is not None:
            _render_report("python (fastjsonschema)", fjs_report)
        elif not args.node_only and not args.skip_fastjsonschema:
            print(
                "fastjsonschema side: SKIPPED (library not importable)"
            )
        if real_pipeline_report is not None:
            _render_report(
                "wat.verify.manifest_v2.verify_real_manifest_file",
                real_pipeline_report,
            )
        if signed_pipeline_report is not None:
            _render_report(
                "wat.verify.manifest_v2.verify_real_manifest_file (signed cohort)",
                signed_pipeline_report,
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
    if fjs_report and fjs_report["mismatched"] > 0:
        fail = True
        print(
            f"fastjsonschema validator: {fjs_report['mismatched']} of "
            f"{fjs_report['total']} vectors mismatched expected verdict",
            file=sys.stderr,
        )

    # N-way parity (covers 2 or 3 validators depending on environment).
    participating = [
        r for r in (py_report, node_report, fjs_report) if r is not None
    ]
    if len(participating) >= 2:
        parity_ok, diffs = compare_reports_multi(participating)
        if not parity_ok:
            fail = True
            print("CROSS-TOOL PARITY VIOLATION:", file=sys.stderr)
            for d in diffs:
                print(f"  {d}", file=sys.stderr)
        else:
            tools = ", ".join(sorted(r["tool"] for r in participating))
            if cohort_tag is not None:
                label = f"real-{cohort_tag} cross-tool"
            else:
                label = "cross-tool"
            total = participating[0]["total"]
            print(
                f"{label} parity OK ({total} vectors, "
                f"{len(participating)} validators: {tools})"
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

    if signed_pipeline_report is not None:
        if signed_pipeline_report["mismatched"] > 0:
            fail = True
            print(
                f"verify_real_manifest_file (signed cohort): "
                f"{signed_pipeline_report['mismatched']} of "
                f"{signed_pipeline_report['total']} hour-receipts failed",
                file=sys.stderr,
            )
            for r in signed_pipeline_report["results"]:
                if not r["matched"]:
                    print(
                        f"  {r['name']}: fields={r['fields_ok']} "
                        f"integrity={r['integrity_ok']} "
                        f"ots={r['ots_anchor_ok']} "
                        f"sig={r['signature_status']!r} "
                        f"reason={r['failure_reason']!r}",
                        file=sys.stderr,
                    )
        else:
            # Every hour-receipt's signature_status should be "verified"
            # (the cohort was freshly hand-signed with the matching key).
            # Surface the per-hour sig-status so the operator sees the
            # gate result, not just an aggregate OK.
            sig_statuses = sorted(
                {r["signature_status"] for r in signed_pipeline_report["results"]}
            )
            print(
                f"verify_real_manifest_file (signed cohort) OK "
                f"({signed_pipeline_report['total']} hour-receipts, "
                f"signature_status={sig_statuses})"
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
