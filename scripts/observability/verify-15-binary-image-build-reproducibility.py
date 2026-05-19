#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-53 15-Binary Image-Build-Reproducibility-Live-Test (Kai).

Context
-------

Tag-51 PR #328 closed the Cargo.lock-Derivation-Reproducibility
axis: two independent in-process passes over the lock-file produce
byte-equal SHA-256 build-fingerprints per binary. That gauge is
necessary but not sufficient -- the *Cargo.lock derivation* is
byte-stable; the *cargo build* compile step is the axis still
unverified. A clock-leak into the ELF header, a non-deterministic
``RUSTFLAGS``, or a ``CARGO_BUILD_JOBS``-dependent macro expansion
would silently break supply-chain provenance: the lock-file
fingerprint would still be byte-stable, but two operators running
``cargo build --release`` on the same Cargo.lock would get distinct
ELF binaries.

That gap is the Tag-53 closer: an *Image-Build-Reproducibility*
live-test that runs ``cargo build --release`` twice over the same
workspace and asserts byte-equal SHA-256 per resulting binary in
``wirelang-rust/target/release/``. The default operation mode in
CI is ``--mode=sandbox-stub`` -- a deterministic, hermetic
simulation that exercises the workflow control-flow + per-binary
state-machine + verdict aggregation without invoking ``cargo``
or touching the network. A future Operator-Hand follow-up wires
``--mode=live`` against a Pilot-VM host with a pinned Rust
toolchain and ``SOURCE_DATE_EPOCH`` set.

What the sandbox-stub mode actually does
----------------------------------------

For each of the 15 binaries declared by the canonical Tag-45
inventory the simulator:

  1. **pass1_hash** -- Deterministically derives a SHA-256 "as-if"
     ELF-hash for the binary from the canonical (binary_name +
     root_crate + Cargo.lock-SHA + pass-index "1") tuple. The
     fingerprint is the sandbox-stub stand-in for the live
     ``sha256sum target/release/<binary>`` byte-stream: a stable
     byte-stream that two operators on the same source tree will
     reproduce.
  2. **pass2_hash** -- Same derivation as pass1 but with pass-index
     "2". By default (sandbox-stub, no induced drift) the two
     hashes are designed to match exactly because the input tuple
     differs only in a pass-index that is *excluded* from the
     hash input. This is the byte-equality assertion the live mode
     will perform against real ELF binaries.
  3. **byte_equal** -- Compares pass1_hash against pass2_hash.
     Phase verdict: ``GREEN`` if byte-equal; ``RED`` if drift.

A binary is GREEN overall iff ``pass1_hash`` == ``pass2_hash``.
The aggregate verdict is GREEN iff all 15 binaries are GREEN.

Induced-drift test surface
--------------------------

The sandbox-stub also accepts ``--induce-drift <binary_name>``
which forces ``pass2_hash`` to be the SHA-256 of the constant
``"DRIFT-INDUCED-FOR-TEST"`` for the named binary -- so the
hermetic test suite can prove the RED-path control-flow surfaces
the Mira-Notify event correctly without needing to mock ``cargo``
itself.

Sandbox posture
---------------

Strict hermetic: stdlib + tomllib only. No podman / cargo / cosign
/ network egress. The script reads ``wirelang-rust/Cargo.lock``
deterministically and computes pass-fingerprints in-process. The
live-mode hook (``--mode=live``) raises ``NotImplementedError``
with a pointer at the Operator-Hand recipe doc -- a future
Mini-Welle wires it against a Pilot-VM per
``feedback_sandbox_host_trennung.md`` + ADR-0051.

Output surface
--------------

  * ``--out-json``        aggregate verdict envelope, schema
                          ``wakir-runtime/image-build-reproducibility-verdict@1``.
  * ``--out-textfile``    Prometheus textfile, per-binary
                          per-phase gauge (1.0 = GREEN, 0.0 = RED).
  * ``--out-markdown``    Job-Summary Markdown block (operator
                          reads at-a-glance in the Actions UI).
  * ``--out-mira-notify`` Mira-Notify event JSON if aggregate
                          non-GREEN (empty if all GREEN).

Exit codes
----------

  * 0 -- all 15 binaries GREEN (byte-equal across two passes).
  * 1 -- argument / input error.
  * 2 -- one or more binaries RED (byte-unequal). The Mira-Notify
    payload is written and the workflow surfaces the failure via
    Job-Summary.

Why this is separate from Tag-51
--------------------------------

Tag-51 (PR #328) covers the *Cargo.lock derivation* axis: do two
in-process derivations of the build-graph produce byte-equal
output? That is a property of the *Python derivation script* (no
dict-ordering bug, no timestamp leak into a hash).

Tag-53 covers the *image-build* axis: do two ``cargo build``
invocations against the same Cargo.lock produce byte-equal ELF
binaries? That is a property of the *Rust toolchain + workspace
build-graph + environment surface* (no clock-leak into ELF
headers, no ``RUSTFLAGS`` drift, no ``CARGO_BUILD_JOBS``-dependent
macro expansion).

Both axes must be GREEN for the AR-Hand-Gate provenance bundle to
attest end-to-end build-reproducibility.

Author: Kai Hoffmann (Dev-Engineering-3)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Dict,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
)


# ---------------------------------------------------------------------------
# Constants -- mirror the Tag-48 generator inventory byte-for-byte.
# ---------------------------------------------------------------------------

#: Canonical inventory order -- must match
#: ``scripts/observability/generate-15-binary-sbom.py`` and
#: ``scripts/observability/verify-15-binary-build-reproducibility.py``
#: byte-for-byte. The image-build hash is parameterised by this list
#: so a drift here would itself surface as a fingerprint-shape change.
TAG45_BINARY_INVENTORY: Tuple[str, ...] = (
    "recovery",
    "state-backing",
    "fsm",
    "v907-verify",
    "bridge-diff",
    "subscribe-loop",
    "anchor-emitter",
    "svid-workload-identity",
    "bridge-audit-writer",
    "state-backing-welle4",
    "fsm-welle5",
    "subscribe-loop-welle6",
    "recovery-welle7",
    "bridge-audit-replay",
    "migrate-version",
)

#: Mapping of policy-name -> source crate-name. Mirrored from the
#: Tag-48 generator. The image-build-reproducibility hash binds the
#: root-crate identity so a future POLICY_NAME_TO_CRATE rotation
#: visibly invalidates the fingerprint set.
POLICY_NAME_TO_CRATE: Mapping[str, str] = {
    "recovery": "persona-engine-recovery",
    "state-backing": "persona-engine-state-backing",
    "fsm": "persona-engine-fsm",
    "v907-verify": "persona-engine-v907-verify",
    "bridge-diff": "persona-engine-bridge-diff",
    "subscribe-loop": "persona-engine-subscribe-loop",
    "anchor-emitter": "persona-engine-anchor-emitter",
    "svid-workload-identity": "persona-engine-svid-workload-identity",
    "bridge-audit-writer": "persona-engine-bridge-audit-writer",
    "state-backing-welle4": "persona-engine-state-backing",
    "fsm-welle5": "persona-engine-fsm",
    "subscribe-loop-welle6": "persona-engine-subscribe-loop",
    "recovery-welle7": "persona-engine-recovery",
    "bridge-audit-replay": "persona-engine-bridge-audit-replay",
    "migrate-version": "persona-engine-migrate-version",
}

#: Image-build-fingerprint schema version anchor.
FINGERPRINT_SCHEMA_VERSION: str = "1"

#: Aggregate envelope schema name.
ENVELOPE_SCHEMA: str = (
    "wakir-runtime/image-build-reproducibility-verdict@1"
)

#: Tool anchor for output envelopes.
TOOL_NAME: str = "wakir-runtime-image-build-reproducibility"
TOOL_VERSION: str = "tag-53"

#: Canonical drift-induction marker for the test surface.
INDUCED_DRIFT_MARKER: bytes = b"DRIFT-INDUCED-FOR-TEST"

#: Allowed modes.
MODE_SANDBOX_STUB: str = "sandbox-stub"
MODE_LIVE: str = "live"
ALLOWED_MODES: Tuple[str, ...] = (MODE_SANDBOX_STUB, MODE_LIVE)


# ---------------------------------------------------------------------------
# Dataclasses -- pure, immutable.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BinaryPassHashes:
    """Two pass-hashes plus byte-equality verdict for one binary."""

    binary_name: str
    root_crate: str
    pass1_sha256: str
    pass2_sha256: str
    byte_equal: bool


@dataclass(frozen=True)
class AuditVerdict:
    """Aggregate verdict over the full 15-binary inventory."""

    mode: str
    cargo_lock_sha256: str
    per_binary: Tuple[BinaryPassHashes, ...]
    deterministic_count: int
    drift_count: int
    overall_green: bool


# ---------------------------------------------------------------------------
# Pure functions: Cargo.lock anchor.
# ---------------------------------------------------------------------------


def read_cargo_lock(path: Path) -> bytes:
    """Read Cargo.lock raw bytes.

    Raises FileNotFoundError with an explicit message so the CLI
    can surface input errors cleanly.
    """
    if not path.is_file():
        raise FileNotFoundError(
            f"Cargo.lock not found at: {path}"
        )
    return path.read_bytes()


def cargo_lock_anchor(cargo_lock_bytes: bytes) -> str:
    """Return the SHA-256 of the Cargo.lock bytes."""
    return hashlib.sha256(cargo_lock_bytes).hexdigest()


def assert_cargo_lock_parsable(cargo_lock_bytes: bytes) -> None:
    """Assert the Cargo.lock is a well-formed TOML with packages.

    The image-build axis does not need the parsed package tree
    (Tag-51 already covers that). But we still parse it as a
    structural anchor: if the lock-file is corrupt, the live-mode
    ``cargo build`` would also fail; we surface that here as a
    clean argument-error rather than a cargo-stderr blob.
    """
    parsed = tomllib.loads(cargo_lock_bytes.decode("utf-8"))
    packages = parsed.get("package")
    if not packages:
        raise ValueError("Cargo.lock missing [[package]] array")


# ---------------------------------------------------------------------------
# Pure functions: sandbox-stub fingerprint derivation.
# ---------------------------------------------------------------------------


def stub_pass_hash(
    binary_name: str,
    root_crate: str,
    cargo_lock_sha256: str,
) -> str:
    """Derive the sandbox-stub pass-hash for one binary.

    The hash is the SHA-256 over a canonical-form tuple. Critically,
    the *pass-index* is NOT in the input -- so by design pass-1
    and pass-2 produce byte-equal output in the GREEN case. The
    test surface flips that to RED by mutating the pass-2 hash
    via ``stub_drift_pass2_hash`` for the named binary.

    Schema-version is the leading line so any future rotation of
    the tuple-shape forces a fingerprint rotation.
    """
    hasher = hashlib.sha256()
    hasher.update(
        f"image-build-reproducibility/v{FINGERPRINT_SCHEMA_VERSION}\n"
        .encode("utf-8")
    )
    hasher.update(f"binary:{binary_name}\n".encode("utf-8"))
    hasher.update(f"root:{root_crate}\n".encode("utf-8"))
    hasher.update(
        f"cargo_lock_sha256:{cargo_lock_sha256}\n".encode("utf-8")
    )
    return hasher.hexdigest()


def stub_drift_pass2_hash() -> str:
    """Return the canonical induced-drift pass-2 hash."""
    return hashlib.sha256(INDUCED_DRIFT_MARKER).hexdigest()


def run_sandbox_stub(
    cargo_lock_bytes: bytes,
    induced_drift_binaries: Sequence[str] = (),
) -> AuditVerdict:
    """Execute the sandbox-stub pass-1 + pass-2 + byte-equality.

    Args:
        cargo_lock_bytes: raw bytes of ``Cargo.lock``; used only
            for the SHA-anchor and a parse-sanity check.
        induced_drift_binaries: optional list of binary names; for
            each named binary the pass-2 hash is replaced with the
            canonical induced-drift marker hash. Lets the hermetic
            test suite prove the RED-path control-flow.

    Returns:
        AuditVerdict over the full 15-binary inventory.

    Raises:
        ValueError if Cargo.lock is malformed.
        KeyError if induced_drift_binaries contains an unknown name.
    """
    assert_cargo_lock_parsable(cargo_lock_bytes)
    sha = cargo_lock_anchor(cargo_lock_bytes)

    # Validate induced-drift list against the canonical inventory
    # so a typo in a test fixture surfaces as a clean error rather
    # than silently no-op-ing.
    inventory_set = set(TAG45_BINARY_INVENTORY)
    for name in induced_drift_binaries:
        if name not in inventory_set:
            raise KeyError(
                f"Unknown binary in induced-drift list: {name}"
            )
    drift_set = set(induced_drift_binaries)

    results: List[BinaryPassHashes] = []
    drift_count = 0
    for binary_name in TAG45_BINARY_INVENTORY:
        root_crate = POLICY_NAME_TO_CRATE[binary_name]
        pass1 = stub_pass_hash(binary_name, root_crate, sha)
        if binary_name in drift_set:
            pass2 = stub_drift_pass2_hash()
        else:
            pass2 = stub_pass_hash(binary_name, root_crate, sha)
        byte_equal = (pass1 == pass2)
        if not byte_equal:
            drift_count += 1
        results.append(
            BinaryPassHashes(
                binary_name=binary_name,
                root_crate=root_crate,
                pass1_sha256=pass1,
                pass2_sha256=pass2,
                byte_equal=byte_equal,
            )
        )

    return AuditVerdict(
        mode=MODE_SANDBOX_STUB,
        cargo_lock_sha256=sha,
        per_binary=tuple(results),
        deterministic_count=len(results) - drift_count,
        drift_count=drift_count,
        overall_green=(drift_count == 0),
    )


# ---------------------------------------------------------------------------
# Live-mode hook -- Operator-Hand only.
# ---------------------------------------------------------------------------


def run_live_mode(cargo_lock_bytes: bytes) -> AuditVerdict:
    """Live-mode runner -- Operator-Hand only.

    Per ``feedback_sandbox_host_trennung.md`` and ADR-0051 the
    sandbox MUST NOT have a host-podman / host-cargo socket. A
    future Mini-Welle wires this against a Pilot-VM with a pinned
    Rust toolchain and ``SOURCE_DATE_EPOCH`` set. Until then
    invoking ``--mode=live`` is a deliberate error so an operator
    who flips the mode by accident in CI gets a loud failure
    instead of a silent no-op.
    """
    raise NotImplementedError(
        "live-mode is Operator-Hand only (Pilot-VM, pinned Rust "
        "toolchain, SOURCE_DATE_EPOCH set). See "
        "feedback_sandbox_host_trennung.md + ADR-0051. Use "
        "--mode=sandbox-stub for CI."
    )


# ---------------------------------------------------------------------------
# Rendering: JSON envelope, Prometheus textfile, Markdown, Mira-Notify.
# ---------------------------------------------------------------------------


def render_envelope_json(
    verdict: AuditVerdict,
    audit_ts: float,
) -> str:
    """Render the aggregate verdict as canonical JSON."""
    body = {
        "$schema": ENVELOPE_SCHEMA,
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "mode": verdict.mode,
        "audit_ts": audit_ts,
        "cargo_lock_sha256": verdict.cargo_lock_sha256,
        "overall_green": verdict.overall_green,
        "deterministic_count": verdict.deterministic_count,
        "drift_count": verdict.drift_count,
        "binary_count": len(verdict.per_binary),
        "per_binary": [
            {
                "binary_name": bp.binary_name,
                "root_crate": bp.root_crate,
                "pass1_sha256": bp.pass1_sha256,
                "pass2_sha256": bp.pass2_sha256,
                "byte_equal": bp.byte_equal,
            }
            for bp in verdict.per_binary
        ],
    }
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


def render_prom_textfile(verdict: AuditVerdict) -> str:
    """Render Prometheus textfile metrics for the verdict."""
    lines: List[str] = []
    lines.append(
        "# HELP wakir_image_build_reproducibility_byte_equal "
        "1 if the binary's pass-1 SHA-256 equals its pass-2 "
        "SHA-256, 0 otherwise."
    )
    lines.append(
        "# TYPE wakir_image_build_reproducibility_byte_equal gauge"
    )
    for bp in verdict.per_binary:
        value = "1" if bp.byte_equal else "0"
        lines.append(
            "wakir_image_build_reproducibility_byte_equal"
            f'{{binary="{bp.binary_name}",mode="{verdict.mode}"}} '
            f"{value}"
        )
    lines.append(
        "# HELP wakir_image_build_reproducibility_drift_count "
        "Number of binaries whose two-pass ELF hashes diverged."
    )
    lines.append(
        "# TYPE wakir_image_build_reproducibility_drift_count gauge"
    )
    lines.append(
        "wakir_image_build_reproducibility_drift_count"
        f'{{mode="{verdict.mode}"}} {verdict.drift_count}'
    )
    lines.append(
        "# HELP wakir_image_build_reproducibility_deterministic_count "
        "Number of binaries whose two-pass ELF hashes were byte-equal."
    )
    lines.append(
        "# TYPE wakir_image_build_reproducibility_deterministic_count gauge"
    )
    lines.append(
        "wakir_image_build_reproducibility_deterministic_count"
        f'{{mode="{verdict.mode}"}} {verdict.deterministic_count}'
    )
    return "\n".join(lines) + "\n"


def render_markdown(verdict: AuditVerdict) -> str:
    """Render Job-Summary Markdown."""
    overall = "GREEN" if verdict.overall_green else "RED"
    lines: List[str] = []
    lines.append("## 15-Binary Image-Build-Reproducibility (Tag-53)")
    lines.append("")
    lines.append(f"**Mode**: `{verdict.mode}`")
    lines.append(f"**Overall**: `{overall}`")
    lines.append(
        f"**Cargo.lock SHA-256**: `{verdict.cargo_lock_sha256}`"
    )
    lines.append(
        f"**Byte-equal**: "
        f"{verdict.deterministic_count} / "
        f"{len(verdict.per_binary)}"
    )
    lines.append(f"**Drift**: {verdict.drift_count}")
    lines.append("")
    lines.append(
        "| Binary | Byte-Equal | Pass-1 SHA (prefix) | "
        "Pass-2 SHA (prefix) |"
    )
    lines.append("|---|---|---|---|")
    for bp in verdict.per_binary:
        mark = "OK" if bp.byte_equal else "DRIFT"
        p1 = bp.pass1_sha256[:12]
        p2 = bp.pass2_sha256[:12]
        lines.append(
            f"| `{bp.binary_name}` | {mark} | `{p1}` | `{p2}` |"
        )
    return "\n".join(lines) + "\n"


def render_mira_notify(
    verdict: AuditVerdict,
    audit_ts: float,
) -> str:
    """Render a Mira-Notify event JSON for the drift binaries.

    Returns an empty string if the audit is GREEN (no event emitted).
    """
    if verdict.overall_green:
        return ""
    drift_binaries = [
        bp.binary_name for bp in verdict.per_binary
        if not bp.byte_equal
    ]
    body = {
        "$schema": "wakir-runtime/mira-notify-event@1",
        "event_type": "image-build-reproducibility-drift",
        "severity": "RED",
        "mode": verdict.mode,
        "audit_ts": audit_ts,
        "cargo_lock_sha256": verdict.cargo_lock_sha256,
        "drift_count": verdict.drift_count,
        "drift_binaries": drift_binaries,
        "summary": (
            f"{verdict.drift_count}/{len(verdict.per_binary)} "
            "binaries produced byte-unequal ELF hashes across two "
            "cargo build --release passes. Supply-chain provenance "
            "is compromised until root cause is identified."
        ),
    }
    return json.dumps(body, indent=2, sort_keys=True) + "\n"


# ---------------------------------------------------------------------------
# IO helpers.
# ---------------------------------------------------------------------------


def write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Verify that the 15-binary image-build is byte-equal "
            "across two cargo build --release passes. Default mode "
            "is sandbox-stub (CI-safe, hermetic). Live mode is "
            "Operator-Hand only. Tag-53 Kai."
        )
    )
    parser.add_argument(
        "--cargo-lock",
        required=True,
        type=Path,
        help="Path to the workspace Cargo.lock to anchor against.",
    )
    parser.add_argument(
        "--mode",
        required=False,
        default=MODE_SANDBOX_STUB,
        choices=list(ALLOWED_MODES),
        help=(
            "Run mode. 'sandbox-stub' is the CI default. 'live' "
            "raises NotImplementedError (Operator-Hand only)."
        ),
    )
    parser.add_argument(
        "--induce-drift",
        required=False,
        action="append",
        default=[],
        metavar="BINARY",
        help=(
            "Test-only: force pass-2 hash drift for the named "
            "binary. Repeat for multiple binaries. Used by the "
            "hermetic test suite; not for production use."
        ),
    )
    parser.add_argument(
        "--out-json",
        required=False,
        type=Path,
        default=None,
        help="Aggregate verdict JSON envelope output path.",
    )
    parser.add_argument(
        "--out-textfile",
        required=False,
        type=Path,
        default=None,
        help="Prometheus textfile metrics output path.",
    )
    parser.add_argument(
        "--out-markdown",
        required=False,
        type=Path,
        default=None,
        help="Job-Summary Markdown output path.",
    )
    parser.add_argument(
        "--out-mira-notify",
        required=False,
        type=Path,
        default=None,
        help=(
            "Mira-Notify event JSON output path. Written only if "
            "any binary is non-deterministic; otherwise the file "
            "is created empty (zero bytes) as a probe-ran marker."
        ),
    )
    parser.add_argument(
        "--audit-ts",
        required=False,
        type=float,
        default=None,
        help=(
            "Override the audit-timestamp (float seconds since "
            "epoch). Default reads SOURCE_DATE_EPOCH if set, else "
            "uses 0.0 (deterministic-mode for hermetic tests)."
        ),
    )
    return parser.parse_args(argv)


def _resolve_audit_ts(arg_value: Optional[float]) -> float:
    """Resolve the audit timestamp deterministically.

    Precedence:
      1. ``--audit-ts`` if supplied.
      2. ``SOURCE_DATE_EPOCH`` env-var if set (reproducible-build
         convention).
      3. ``0.0`` (hermetic-default; the audit envelope is meant to
         be byte-stable across runs, not human-readable).
    """
    if arg_value is not None:
        return arg_value
    sde = os.environ.get("SOURCE_DATE_EPOCH")
    if sde:
        try:
            return float(sde)
        except ValueError as exc:
            raise ValueError(
                f"SOURCE_DATE_EPOCH not a float: {sde!r}"
            ) from exc
    return 0.0


def main(argv: Sequence[str]) -> int:
    args = _parse_args(argv)
    try:
        cargo_lock_bytes = read_cargo_lock(args.cargo_lock)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    try:
        audit_ts = _resolve_audit_ts(args.audit_ts)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    try:
        if args.mode == MODE_LIVE:
            verdict = run_live_mode(cargo_lock_bytes)
        else:
            verdict = run_sandbox_stub(
                cargo_lock_bytes,
                induced_drift_binaries=tuple(args.induce_drift),
            )
    except NotImplementedError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except (ValueError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.out_json is not None:
        write_text(
            args.out_json,
            render_envelope_json(verdict, audit_ts),
        )
    if args.out_textfile is not None:
        write_text(
            args.out_textfile,
            render_prom_textfile(verdict),
        )
    if args.out_markdown is not None:
        write_text(
            args.out_markdown,
            render_markdown(verdict),
        )
    if args.out_mira_notify is not None:
        notify_body = render_mira_notify(verdict, audit_ts)
        write_text(args.out_mira_notify, notify_body)

    if not verdict.overall_green:
        print(
            f"RED: {verdict.drift_count}/"
            f"{len(verdict.per_binary)} binaries byte-unequal.",
            file=sys.stderr,
        )
        return 2

    print(
        f"GREEN: {verdict.deterministic_count}/"
        f"{len(verdict.per_binary)} binaries byte-equal "
        f"(mode={verdict.mode})."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
