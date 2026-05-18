# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic tests for ``scripts/image-pin-idempotent-resolver.sh``.

Phase-2 Sprint-9 Tag-5 CI-hygiene: the resolver MUST be idempotent.
Concrete contract under test:

* First-run on a placeholder-only repo: drift detected (exit 10),
  files mutated.
* Second-run on the now-resolved repo with the SAME forced digest:
  no drift (exit 0), files unchanged byte-for-byte.
* Run on a half-resolved repo (some pins placeholder, some real):
  resolver only mutates the still-pending entries; the already-
  resolved ones stay byte-identical.
* ``--print-only`` exits 10 on drift but does NOT mutate any file.
* A live-digest that differs from the committed pin is treated as
  drift (the cron-cycle path: upstream re-push detection).

The sandbox boundary is preserved by ``--digest-source env`` which
reads ``FORCE_<GROUP>_DIGEST`` env vars instead of calling crane.
No network egress under test.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = REPO_ROOT / "scripts" / "image-pin-idempotent-resolver.sh"


# A static, syntactically valid sha256 for the five pin groups. Picked
# to be deterministic and obviously fake.
#
# Sprint-10 Tag-4: ``FORCE_WAKIR_PERSONA_ENGINE_DIGEST`` added for the
# new ``wakir_persona_engine`` PINS row that closes the ADR-0058
# Schritt 9 image-availability gap (Quadlet
# ``quadlet/wakir-persona-tomas.container`` line 86). The
# ``infra/persona-engine/Containerfile`` was also added to the
# ``python`` row (shares the python:3.13-slim base with the
# provisioner Containerfile).
FAKE_DIGESTS = {
    "FORCE_SPIRE_SERVER_DIGEST":         "sha256:" + "a" * 64,
    "FORCE_SPIRE_AGENT_DIGEST":          "sha256:" + "b" * 64,
    "FORCE_PYTHON_DIGEST":               "sha256:" + "c" * 64,
    "FORCE_WAKIR_PROVISIONER_DIGEST":    "sha256:" + "d" * 64,
    "FORCE_WAKIR_PERSONA_ENGINE_DIGEST": "sha256:" + "e" * 64,
}

PIN_TARGETS = [
    "infra/spire/federation/quadlet/wakir-spire-server-federation.container",
    "quadlet/wakir-spire-server.container",
    "infra/spire/agent/quadlet/wakir-spire-agent-federation.container",
    "quadlet/wakir-spire-agent.container",
    "infra/spire/federation/provisioner/Containerfile",
    "infra/persona-engine/Containerfile",
    "quadlet/wakir-nats-kv-bucket-init.container",
    "quadlet/wakir-persona-tomas.container",
]


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot(root: Path) -> dict[str, str]:
    out = {}
    for rel in PIN_TARGETS:
        f = root / rel
        if f.is_file():
            out[rel] = _file_digest(f)
    return out


@pytest.fixture
def repo_copy(tmp_path: Path) -> Path:
    """Copy the pin-bearing subset of the repo into a tmp tree.

    Hermetic-test isolation: we mutate file contents inside the tmp
    copy, never the repo root. A re-run of the test suite against the
    same repo always sees identical input.
    """
    dst = tmp_path / "repo"
    dst.mkdir()
    for rel in PIN_TARGETS:
        src = REPO_ROOT / rel
        if not src.is_file():
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return dst


def _run_resolver(root: Path, env: dict[str, str], extra: list[str] | None = None) -> subprocess.CompletedProcess:
    cmd = [
        "bash",
        str(RESOLVER),
        "--root", str(root),
        "--digest-source", "env",
    ] + (extra or [])
    full_env = {**os.environ, **env}
    return subprocess.run(
        cmd,
        env=full_env,
        check=False,
        capture_output=True,
        text=True,
    )


# ----------------------------------------------------------------------
# Resolver-binary invariants.
# ----------------------------------------------------------------------

def test_resolver_script_exists_and_executable() -> None:
    assert RESOLVER.is_file(), f"missing resolver: {RESOLVER}"
    st = RESOLVER.stat()
    assert st.st_mode & stat.S_IXUSR, "resolver must be executable"


def test_resolver_bash_syntax_clean() -> None:
    rc = subprocess.run(["bash", "-n", str(RESOLVER)], check=False)
    assert rc.returncode == 0, "bash -n failed on resolver"


def test_resolver_help() -> None:
    rc = subprocess.run(
        ["bash", str(RESOLVER), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0
    # Help text MUST document the exit-code contract — the workflow
    # depends on it.
    assert "0   = no drift" in rc.stdout or "0 = no drift" in rc.stdout
    assert "10  = drift detected" in rc.stdout or "10 = drift detected" in rc.stdout


# ----------------------------------------------------------------------
# Idempotency invariants — the core of Sprint-9 Tag-5 Teil 2.
# ----------------------------------------------------------------------

def test_first_run_resolves_placeholders(repo_copy: Path) -> None:
    pre = _snapshot(repo_copy)
    proc = _run_resolver(repo_copy, FAKE_DIGESTS)
    # Drift sentinel (10) because placeholders count as drift.
    assert proc.returncode == 10, (
        f"expected drift sentinel 10, got {proc.returncode}\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    post = _snapshot(repo_copy)
    # At least one file changed.
    diffs = [k for k in pre if pre[k] != post.get(k)]
    assert diffs, "first run should have mutated at least one pin file"


def test_second_run_is_noop(repo_copy: Path) -> None:
    # Apply first.
    first = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert first.returncode == 10
    state_after_first = _snapshot(repo_copy)

    # Re-run with the EXACT SAME forced digests. Must be a no-op.
    second = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert second.returncode == 0, (
        f"expected idempotent no-op (rc=0), got {second.returncode}\n"
        f"stdout:\n{second.stdout}\nstderr:\n{second.stderr}"
    )
    state_after_second = _snapshot(repo_copy)
    assert state_after_first == state_after_second, (
        "idempotent re-run mutated files; this is the bug Sprint-9 "
        "Tag-5 Teil 2 was meant to close"
    )


def test_third_run_still_noop(repo_copy: Path) -> None:
    # Belt-and-suspenders: many cron cycles in a row must all be no-op.
    _run_resolver(repo_copy, FAKE_DIGESTS)
    state_1 = _snapshot(repo_copy)
    _run_resolver(repo_copy, FAKE_DIGESTS)
    _run_resolver(repo_copy, FAKE_DIGESTS)
    state_3 = _snapshot(repo_copy)
    assert state_1 == state_3


def test_drift_to_new_live_digest(repo_copy: Path) -> None:
    # Cycle 1: resolve with FAKE_DIGESTS, files now carry those.
    _run_resolver(repo_copy, FAKE_DIGESTS)
    # Cycle 2: upstream re-push — live digest changes for one group.
    rotated = dict(FAKE_DIGESTS)
    rotated["FORCE_PYTHON_DIGEST"] = "sha256:" + "e" * 64
    proc = _run_resolver(repo_copy, rotated)
    assert proc.returncode == 10, (
        "rotation of an upstream digest must trigger drift sentinel"
    )
    # The mutated file is the Containerfile carrying the python pin.
    containerfile = repo_copy / "infra/spire/federation/provisioner/Containerfile"
    assert "e" * 64 in containerfile.read_text()


# ----------------------------------------------------------------------
# --print-only is non-mutating.
# ----------------------------------------------------------------------

def test_print_only_does_not_mutate_files(repo_copy: Path) -> None:
    pre = _snapshot(repo_copy)
    proc = _run_resolver(repo_copy, FAKE_DIGESTS, extra=["--print-only"])
    # Still emits drift sentinel because placeholders count as drift.
    assert proc.returncode == 10
    post = _snapshot(repo_copy)
    assert pre == post, "--print-only must not mutate any file"


def test_print_only_then_apply_is_consistent(repo_copy: Path) -> None:
    # print-only first, then real apply — must arrive at same final
    # state as a direct apply.
    direct = repo_copy
    indirect_root = direct.parent / "indirect"
    shutil.copytree(direct, indirect_root)

    _run_resolver(direct, FAKE_DIGESTS)
    _run_resolver(indirect_root, FAKE_DIGESTS, extra=["--print-only"])
    _run_resolver(indirect_root, FAKE_DIGESTS)

    s_direct = _snapshot(direct)
    s_indirect = _snapshot(indirect_root)
    assert s_direct == s_indirect


# ----------------------------------------------------------------------
# Resolver-side argument validation.
# ----------------------------------------------------------------------

def test_resolver_rejects_bad_digest_source(repo_copy: Path) -> None:
    proc = subprocess.run(
        ["bash", str(RESOLVER), "--root", str(repo_copy),
         "--digest-source", "magic"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


def test_resolver_rejects_missing_root() -> None:
    proc = subprocess.run(
        ["bash", str(RESOLVER), "--root", "/nonexistent-xyzzy"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0


# ----------------------------------------------------------------------
# Workflow-side wiring — keep the CI wrapper in sync with the script.
# ----------------------------------------------------------------------

def test_workflow_yaml_present() -> None:
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    assert wf.is_file()


def test_workflow_calls_resolver_script() -> None:
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    text = wf.read_text(encoding="utf-8")
    assert "scripts/image-pin-idempotent-resolver.sh" in text


def test_workflow_handles_drift_sentinel() -> None:
    # The workflow MUST distinguish drift (exit 10) from real error
    # (exit 1+). Otherwise a real error would silently turn into a PR.
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    text = wf.read_text(encoding="utf-8")
    assert "10)" in text or "10 )" in text, (
        "workflow must branch on exit code 10 (drift sentinel)"
    )


def test_workflow_no_packages_write() -> None:
    # Least-privilege: this workflow neither pushes images nor signs.
    import yaml
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    d = yaml.safe_load(wf.read_text(encoding="utf-8"))
    perms = d.get("permissions", {})
    assert "packages" not in perms, (
        "resolve-image-pins-ci must not request packages: write; that "
        "scope belongs to build-wakir-provisioner only"
    )
    assert "id-token" not in perms, (
        "resolve-image-pins-ci does not sign — no id-token scope"
    )


def test_workflow_requires_contents_write() -> None:
    import yaml
    wf = REPO_ROOT / ".github" / "workflows" / "resolve-image-pins-ci.yml"
    d = yaml.safe_load(wf.read_text(encoding="utf-8"))
    perms = d.get("permissions", {})
    # Needs contents:write to push the auto-branch + open PR.
    assert perms.get("contents") == "write"
    assert perms.get("pull-requests") == "write"


# ----------------------------------------------------------------------
# Sprint-9 Tag-6 — tag-tolerant wakir-provisioner row.
# ----------------------------------------------------------------------

def test_pins_inventory_wakir_provisioner_is_bare_base(repo_copy: Path) -> None:
    """Sprint-9 Tag-6: the wakir-provisioner PINS row MUST use the
    bare image-base (no ``:<tag>`` suffix) so the resolver tolerates
    the tag drift the BSL-Bulk-Edit-Welle introduced (Bug 3, Live-
    Bring-up-2-Bilanz 2026-05-14). Tag-pinned SPIRE / python rows
    stay byte-identical."""
    text = RESOLVER.read_text(encoding="utf-8")
    # Bare-base wakir-provisioner row.
    assert (
        '"wakir_provisioner|ghcr.io/wakir-labs/wakir-provisioner|'
        in text
    ), (
        "PINS inventory must carry the bare wakir-provisioner base "
        "(no :<tag> suffix) for tag-tolerant drift detection"
    )
    # The legacy tag-pinned form must NOT linger.
    assert (
        "ghcr.io/wakir-labs/wakir-provisioner:0.1.2|" not in text
    ), (
        "PINS inventory still carries the legacy tag-pinned "
        "wakir-provisioner row; Sprint-9 Tag-6 contract requires "
        "the bare-base form"
    )


def test_resolver_substitutes_quadlet_with_drifted_tag(
    repo_copy: Path,
) -> None:
    """The resolver MUST detect drift on the bucket-init Quadlet
    EVEN WHEN the tag in the pin differs from any value previously
    hard-coded in the resolver itself. We stage a Quadlet with a
    future-tag form and confirm the resolver substitutes the digest
    while preserving the tag byte-for-byte."""
    quadlet = repo_copy / "quadlet" / "wakir-nats-kv-bucket-init.container"
    quadlet.parent.mkdir(parents=True, exist_ok=True)
    quadlet.write_text(
        "[Container]\n"
        "Image=ghcr.io/wakir-labs/wakir-provisioner:9.9.9-future"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )
    proc = _run_resolver(repo_copy, FAKE_DIGESTS)
    # Drift sentinel: placeholder replaced.
    assert proc.returncode == 10, (
        f"resolver did not detect drift on drifted-tag Quadlet: "
        f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    text = quadlet.read_text()
    assert "DIGEST_PENDING_TOMAS_REVIEW" not in text
    assert (
        "ghcr.io/wakir-labs/wakir-provisioner:9.9.9-future@sha256:"
        + "d" * 64
    ) in text, (
        f"resolver did not preserve the existing tag or substitute "
        f"the digest correctly: {text!r}"
    )


def test_resolver_idempotent_on_drifted_tag(repo_copy: Path) -> None:
    """Re-run on a stable drifted-tag pin MUST be a no-op (rc=0)."""
    quadlet = repo_copy / "quadlet" / "wakir-nats-kv-bucket-init.container"
    quadlet.parent.mkdir(parents=True, exist_ok=True)
    quadlet.write_text(
        "[Container]\n"
        "Image=ghcr.io/wakir-labs/wakir-provisioner:9.9.9-future"
        "@sha256:DIGEST_PENDING_TOMAS_REVIEW\n"
    )
    # First run resolves; second run must be a no-op.
    first = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert first.returncode == 10
    text_after_first = quadlet.read_text()
    second = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert second.returncode == 0, (
        f"idempotent re-run on drifted-tag pin failed: "
        f"stdout={second.stdout!r} stderr={second.stderr!r}"
    )
    assert quadlet.read_text() == text_after_first, (
        "idempotent re-run mutated the drifted-tag Quadlet"
    )


# ----------------------------------------------------------------------
# Sprint-10 Tag-4 — wakir-persona-engine PINS row + generalised
# ``DIGEST_PENDING_<ANNOTATION>`` placeholder regex.
# ----------------------------------------------------------------------

def test_pins_inventory_carries_wakir_persona_engine_row() -> None:
    """The PINS array MUST carry a bare-base ``wakir_persona_engine``
    row so the ADR-0058 Schritt 9 image-availability gap-closer can
    be resolved by the same idempotent workflow as the SPIRE +
    provisioner digests."""
    text = RESOLVER.read_text(encoding="utf-8")
    assert (
        '"wakir_persona_engine|ghcr.io/wakir-labs/wakir-persona-engine|'
        in text
    ), (
        "PINS inventory must carry the bare wakir-persona-engine row "
        "(no :<tag> suffix) so the resolver tolerates the "
        "0.1.0-pilot -> 0.2.0-pilot rotation when the Sprint-Pengine-8 "
        "axis lands the full engine"
    )
    # The row must point at the Tomás-pilot Quadlet (the consumer).
    assert "quadlet/wakir-persona-tomas.container" in text


def test_pins_inventory_python_row_covers_both_containerfiles() -> None:
    """The python:3.13-slim base is shared between the federation-
    provisioner Containerfile and the persona-engine Containerfile;
    the PINS python row MUST resolve both in lockstep so a base-layer
    rotation never leaves them out of sync."""
    text = RESOLVER.read_text(encoding="utf-8")
    assert (
        "infra/spire/federation/provisioner/Containerfile;"
        "infra/persona-engine/Containerfile" in text
    ), (
        "PINS python row must carry both Containerfiles "
        "(provisioner + persona-engine) joined by ';'"
    )


def test_resolver_substitutes_kai_cross_review_placeholder(
    repo_copy: Path,
) -> None:
    """The generalised placeholder regex MUST recognise
    ``sha256:DIGEST_PENDING_KAI_CROSS_REVIEW`` as a placeholder, not
    only the historical ``_TOMAS_REVIEW`` form. We stage a pin with
    the Kai-cross-review annotation and confirm the resolver
    substitutes it byte-precisely."""
    quadlet = repo_copy / "quadlet" / "wakir-persona-tomas.container"
    quadlet.parent.mkdir(parents=True, exist_ok=True)
    quadlet.write_text(
        "[Container]\n"
        "Image=ghcr.io/wakir-labs/wakir-persona-engine:0.1.0-pilot"
        "@sha256:DIGEST_PENDING_KAI_CROSS_REVIEW\n"
    )
    proc = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert proc.returncode == 10, (
        f"resolver did not detect drift on Kai-cross-review "
        f"placeholder: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    text = quadlet.read_text()
    assert "DIGEST_PENDING_KAI_CROSS_REVIEW" not in text
    assert (
        "ghcr.io/wakir-labs/wakir-persona-engine:0.1.0-pilot@sha256:"
        + "e" * 64
    ) in text, (
        f"resolver did not preserve the existing tag or substitute "
        f"the digest correctly: {text!r}"
    )


def test_resolver_substitutes_arbitrary_placeholder_annotation(
    repo_copy: Path,
) -> None:
    """The Sprint-10 Tag-4 generalised regex must accept ANY
    uppercase ``DIGEST_PENDING_<ANNOTATION>`` token — not only the
    two annotations the repo currently uses. We stage a synthetic
    annotation (``_REZA_ZONE_B_REVIEW``) to confirm the regex is
    truly generic and does not silently match-only-known-suffixes."""
    quadlet = repo_copy / "quadlet" / "wakir-persona-tomas.container"
    quadlet.parent.mkdir(parents=True, exist_ok=True)
    quadlet.write_text(
        "[Container]\n"
        "Image=ghcr.io/wakir-labs/wakir-persona-engine:0.1.0-pilot"
        "@sha256:DIGEST_PENDING_REZA_ZONE_B_REVIEW\n"
    )
    proc = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert proc.returncode == 10, (
        f"resolver did not detect drift on synthetic placeholder "
        f"annotation: stdout={proc.stdout!r} stderr={proc.stderr!r}"
    )
    text = quadlet.read_text()
    assert "DIGEST_PENDING_REZA_ZONE_B_REVIEW" not in text
    assert "sha256:" + "e" * 64 in text


def test_resolver_idempotent_on_persona_engine_pin(
    repo_copy: Path,
) -> None:
    """Re-run on a stable persona-engine pin MUST be a no-op (rc=0)
    — same idempotency contract as the provisioner row."""
    first = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert first.returncode == 10
    state_after_first = _snapshot(repo_copy)
    second = _run_resolver(repo_copy, FAKE_DIGESTS)
    assert second.returncode == 0
    state_after_second = _snapshot(repo_copy)
    assert state_after_first == state_after_second, (
        "idempotent re-run mutated files; persona-engine row "
        "violates the Sprint-9 Tag-5 idempotency contract"
    )


def test_persona_engine_containerfile_present() -> None:
    """The Containerfile that the python PINS row points at MUST
    exist on disk — otherwise the resolver silently skips it and the
    image-availability gap stays open."""
    cf = REPO_ROOT / "infra" / "persona-engine" / "Containerfile"
    assert cf.is_file(), (
        f"missing persona-engine Containerfile: {cf}; the python "
        f"PINS row references it but the file is absent"
    )


def test_persona_engine_stub_present_and_executable() -> None:
    """The substrate-stub binary the Containerfile COPYs into the
    image MUST exist + be executable; otherwise the image build
    fails at COPY time."""
    stub = REPO_ROOT / "infra" / "persona-engine" / "bin" / "persona-engine"
    assert stub.is_file(), f"missing stub: {stub}"
    st = stub.stat()
    assert st.st_mode & stat.S_IXUSR, "stub must be executable"


def test_build_workflow_present() -> None:
    """The ``workflow_dispatch``-only build workflow that publishes
    the wakir-persona-engine image MUST be present so the
    Operator-Hand path declared in the README is wired end-to-end."""
    wf = REPO_ROOT / ".github" / "workflows" / "build-wakir-persona-engine.yml"
    assert wf.is_file()
    text = wf.read_text(encoding="utf-8")
    # Manual-only trigger (parity with build-wakir-provisioner.yml).
    assert "workflow_dispatch:" in text
    assert "push:" not in text.split("on:")[1].split("jobs:")[0], (
        "build workflow must not auto-trigger on push events"
    )
    # Builds the persona-engine Containerfile, not provisioner.
    assert "infra/persona-engine/Containerfile" in text
    # Sigstore-keyless sign step present.
    assert "cosign sign" in text


def test_build_workflow_least_privilege_permissions() -> None:
    """Least-privilege scopes — parity with the provisioner build
    workflow. Removing any of these breaks a specific step."""
    import yaml
    wf = REPO_ROOT / ".github" / "workflows" / "build-wakir-persona-engine.yml"
    d = yaml.safe_load(wf.read_text(encoding="utf-8"))
    perms = d.get("permissions", {})
    assert perms.get("contents") == "read"
    assert perms.get("packages") == "write"
    assert perms.get("id-token") == "write"


# ---------------------------------------------------------------------------
# Sprint-Pengine-8 — Real-engine binary + Containerfile.real coverage.
# ---------------------------------------------------------------------------


def test_persona_engine_real_containerfile_present() -> None:
    """Sprint-Pengine-8 ships the real-engine Containerfile alongside
    the stub. Image-tag rotation 0.1.0-pilot -> 0.2.0-pilot picks the
    ``-f infra/persona-engine/Containerfile.real`` build path."""
    cf = REPO_ROOT / "infra" / "persona-engine" / "Containerfile.real"
    assert cf.is_file(), (
        f"missing persona-engine real Containerfile: {cf}; "
        f"Sprint-Pengine-8 image swap path is incomplete"
    )


def test_persona_engine_real_shim_present_and_executable() -> None:
    """The thin entry-point shim for the real engine binary MUST exist
    and be executable; otherwise the Containerfile.real build fails
    at COPY time."""
    shim = (
        REPO_ROOT / "infra" / "persona-engine" / "bin" / "persona-engine-real"
    )
    assert shim.is_file(), f"missing real-engine shim: {shim}"
    st = shim.stat()
    assert st.st_mode & stat.S_IXUSR, "real-engine shim must be executable"


def test_build_workflow_supports_containerfile_input() -> None:
    """The build workflow exposes a ``containerfile`` input so the
    operator can switch between Containerfile (stub) and
    Containerfile.real (real engine) at workflow-dispatch time."""
    wf = REPO_ROOT / ".github" / "workflows" / "build-wakir-persona-engine.yml"
    text = wf.read_text(encoding="utf-8")
    assert "containerfile:" in text, (
        "build workflow must expose a 'containerfile' input"
    )
    # The path is dynamic — Containerfile.real is mentioned.
    assert "Containerfile.real" in text, (
        "build workflow must reference Containerfile.real in its "
        "documentation/dispatch surface so operators see the option"
    )


def test_persona_engine_v0_2_0_package_present() -> None:
    """The wirelang.persona_engine package (real implementation
    sourced into the 0.2.0-pilot image) must be present on disk."""
    pkg = REPO_ROOT / "wirelang" / "persona_engine"
    assert pkg.is_dir(), f"missing persona-engine package dir: {pkg}"
    for required in (
        "__init__.py",
        "lifecycle_state_machine.py",
        "state_backing.py",
        "v907_verify.py",
        "svid_workload_identity.py",
        "bridge_audit_writer.py",
        "recovery_workflow.py",
        "despawn_clean.py",
        "engine.py",
        "cli.py",
    ):
        assert (pkg / required).is_file(), (
            f"missing persona-engine module: {pkg / required}"
        )


def test_persona_engine_version_label_in_containerfile_real() -> None:
    """The Containerfile.real must declare the current image version
    so the GHCR tag and the OCI label match (audit-invariant).

    Tag-48 bump: 0.5.0-pre-cutover -> 0.5.1-pre-cutover for the
    bridge-audit-writer wire-in (10th BackendDecision; manifest at
    wirelang/persona_engine/MANIFEST-0.5.1-pre-cutover.md + pin pack
    at infra/persona-engine/pin-pack-0.5.1-pre-cutover.yaml). The
    engine code itself is byte-stable relative to Sprint-Pengine-13
    on the hot-path; the container-tag rotation tracks the wire-in
    milestone (Tomás Sprint-10 Tag-4 image-pin-idempotent-resolver
    invariant).
    """
    cf = REPO_ROOT / "infra" / "persona-engine" / "Containerfile.real"
    text = cf.read_text(encoding="utf-8")
    assert 'org.opencontainers.image.version="0.5.1-pre-cutover"' in text


def test_real_shim_dispatches_to_cli_main() -> None:
    """The real-engine shim is a thin dispatcher to
    ``wirelang.persona_engine.cli.main``. The shim file is small (<= 60
    lines of code, excluding the BSL header)."""
    shim = (
        REPO_ROOT / "infra" / "persona-engine" / "bin" / "persona-engine-real"
    )
    text = shim.read_text(encoding="utf-8")
    assert "wirelang.persona_engine.cli" in text
    assert "main as cli_main" in text or "from wirelang.persona_engine.cli import main" in text
