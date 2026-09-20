# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``tooling/ci/verify_image_pin_consistency.py``.

The negative control is the point of this module. ``digest-verify
python:3.13-slim`` read one of the three files that pin the python base
layer, and of that file the first match. A change that refreshed only
that one file made the check green while two files stayed on the old
digest — green as a statement about pins the check never looked at.

``test_negative_control_one_of_three_files_updated`` replays exactly
that: three Containerfiles pin the same image, one is moved to a new
digest, and the gate must go **red**. If someone narrows the scan back
to a single file, that test fails, which is the whole reason it is
written as a replay of the defect rather than as an abstract invariant.

The real-tree tests then pin the coverage itself: three python sites,
seven rust sites, seven distroless sites. A future edit that drops a
site from the tree without a matching edit here has to say so.

Hermetic: ``tmp_path`` trees and the repository on disk. No network.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tooling" / "ci"))

import verify_image_pin_consistency as vipc  # noqa: E402


DIGEST_A = "a" * 64
DIGEST_B = "b" * 64

# No SPDX literal in the fixture: a licence identifier written as a
# string payload is what the REUSE-wrap rule exists for, and the
# fixture does not need one.
CONTAINERFILE_TMPL = """FROM docker.io/library/python:3.13-slim@sha256:{digest} AS builder
RUN echo build
"""


def _make_tree(tmp_path: Path, digests: list[str]) -> Path:
    """Three Containerfiles under ``infra/``, one per digest given."""
    for index, digest in enumerate(digests):
        path = tmp_path / "infra" / f"component-{index}" / "Containerfile"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            CONTAINERFILE_TMPL.format(digest=digest), encoding="utf-8"
        )
    return tmp_path


# ======================================================================
# The negative control
# ======================================================================


def test_negative_control_one_of_three_files_updated(tmp_path: Path) -> None:
    """One file refreshed, two left behind — the gate must be RED.

    This is the defect that made the single-file extraction dangerous
    rather than merely incomplete: the green verdict certified pins that
    were not read.
    """
    _make_tree(tmp_path, [DIGEST_B, DIGEST_A, DIGEST_A])

    report = vipc.build_report(tmp_path)

    assert report["verdict"] == "FAIL", (
        "a tree where one of three files carries a different digest for "
        "the same image:tag must fail"
    )
    assert len(report["violations"]) == 1
    violation = report["violations"][0]
    assert violation["reason"] == "divergent-digests"
    assert violation["image"] == "python"
    assert violation["tag"] == "3.13-slim"
    assert sorted(violation["digests"]) == sorted(
        [f"sha256:{DIGEST_A}", f"sha256:{DIGEST_B}"]
    )
    # The report names every site, not just the divergent one: the
    # operator has to see which files disagree to know which is right.
    assert len(violation["sites"]) == 3


def test_negative_control_exits_nonzero(tmp_path: Path) -> None:
    """The CLI, not just the library call, must fail the job."""
    _make_tree(tmp_path, [DIGEST_B, DIGEST_A, DIGEST_A])
    rc = vipc.main(["--repo-root", str(tmp_path), "--quiet"])
    assert rc == 1, "divergent pins must exit 1 so the CI step goes red"


def test_all_three_files_in_lockstep_passes(tmp_path: Path) -> None:
    """The same refresh applied everywhere is the green case."""
    _make_tree(tmp_path, [DIGEST_A, DIGEST_A, DIGEST_A])
    report = vipc.build_report(tmp_path)
    assert report["verdict"] == "PASS"
    assert report["violations"] == []
    groups = {(g["image"], g["tag"]): g for g in report["groups"]}
    assert len(groups[("python", "3.13-slim")]["sites"]) == 3


# ======================================================================
# Boundaries the rule deliberately draws
# ======================================================================


def test_bare_and_library_qualified_references_are_one_group(
    tmp_path: Path,
) -> None:
    """``nats:2.11-alpine`` and ``docker.io/library/nats:2.11-alpine``
    are the same image.

    They are pinned in ``compose/nats.yaml`` and
    ``quadlet/wakir-nats.container`` respectively. A checker that
    compared the literal reference strings would put them in two groups
    of one and never compare them — a coverage gap that looks like
    coverage.
    """
    (tmp_path / "compose").mkdir(parents=True)
    (tmp_path / "quadlet").mkdir(parents=True)
    (tmp_path / "compose" / "nats.yaml").write_text(
        f"services:\n  nats:\n    image: nats:2.11-alpine@sha256:{DIGEST_A}\n",
        encoding="utf-8",
    )
    (tmp_path / "quadlet" / "wakir-nats.container").write_text(
        f"[Container]\nImage=docker.io/library/nats:2.11-alpine@sha256:{DIGEST_B}\n",
        encoding="utf-8",
    )
    report = vipc.build_report(tmp_path)
    assert report["verdict"] == "FAIL", (
        "the bare and the library-qualified reference must be compared "
        "with each other"
    )
    assert report["violations"][0]["image"] == "nats"


def test_placeholder_beside_a_real_digest_is_reported_not_failed(
    tmp_path: Path,
) -> None:
    """An unresolved site is not a wrong site.

    ``DIGEST_PENDING_*`` tokens are owned by
    ``verify_containerfile_base_image_digest.py``, which decides which
    tokens are legal. This check would otherwise fail on a state that is
    merely incomplete, and on 2026-09-21 the tree carries exactly one
    such case (``wakir-provisioner:0.1.2``) under another cross-review
    zone's ownership. It is reported so it stays visible.
    """
    base = tmp_path / "quadlet"
    base.mkdir(parents=True)
    (base / "a.container").write_text(
        f"[Container]\nImage=ghcr.io/x/y:1.0@sha256:{DIGEST_A}\n",
        encoding="utf-8",
    )
    (base / "b.container").write_text(
        "[Container]\nImage=ghcr.io/x/y:1.0@sha256:DIGEST_PENDING_REZA_REVIEW\n",
        encoding="utf-8",
    )
    report = vipc.build_report(tmp_path)
    assert report["verdict"] == "PASS"
    group = report["groups"][0]
    assert group["placeholder_tokens"] == ["DIGEST_PENDING_REZA_REVIEW"]
    assert len(group["sites"]) == 2


def test_commented_out_pins_are_not_compared(tmp_path: Path) -> None:
    """A pin quoted in a comment is documentation, often documentation
    *about* a digest that changed. Comparing it with the live directive
    turns correct historical prose into a red gate — the failure mode
    that gets a lint switched off."""
    path = tmp_path / "infra" / "c" / "Containerfile"
    path.parent.mkdir(parents=True)
    path.write_text(
        f"# was: python:3.13-slim@sha256:{DIGEST_B}\n"
        f"FROM docker.io/library/python:3.13-slim@sha256:{DIGEST_A}\n",
        encoding="utf-8",
    )
    report = vipc.build_report(tmp_path)
    assert report["verdict"] == "PASS"
    assert report["pin_count"] == 1


def test_fixtures_under_tests_directories_are_out_of_scope(
    tmp_path: Path,
) -> None:
    """Test fixtures carry deliberately wrong digests. Scanning them
    would make the gate red for the tests that prove it works."""
    live = tmp_path / "infra" / "c" / "Containerfile"
    live.parent.mkdir(parents=True)
    live.write_text(
        f"FROM docker.io/library/python:3.13-slim@sha256:{DIGEST_A}\n",
        encoding="utf-8",
    )
    fixture = tmp_path / "infra" / "c" / "tests" / "Containerfile"
    fixture.parent.mkdir(parents=True)
    fixture.write_text(
        f"FROM docker.io/library/python:3.13-slim@sha256:{DIGEST_B}\n",
        encoding="utf-8",
    )
    report = vipc.build_report(tmp_path)
    assert report["verdict"] == "PASS"
    assert report["pin_count"] == 1


def test_missing_repo_root_is_a_usage_error(tmp_path: Path) -> None:
    rc = vipc.main(["--repo-root", str(tmp_path / "nope"), "--quiet"])
    assert rc == 2


# ======================================================================
# The real tree
# ======================================================================


@pytest.fixture(scope="module")
def real_report() -> dict:
    return vipc.build_report(REPO_ROOT)


def test_repository_pins_are_self_consistent(real_report: dict) -> None:
    """``main`` must not contradict itself about any image."""
    assert real_report["verdict"] == "PASS", (
        "divergent image pins on the tree: "
        f"{real_report['violations']}"
    )


def _group(report: dict, image: str, tag: str) -> dict:
    for group in report["groups"]:
        if group["image"] == image and group["tag"] == tag:
            return group
    raise AssertionError(f"no pin group for {image}:{tag}")


def test_python_base_layer_has_three_pin_sites(real_report: dict) -> None:
    """The coverage number the old single-file extraction missed.

    If a fourth file starts pinning the python base layer, or one of the
    three stops, this test is where that has to be stated.
    """
    group = _group(real_report, "python", "3.13-slim")
    paths = sorted(site["path"] for site in group["sites"])
    assert paths == [
        "infra/persona-engine/Containerfile",
        "infra/persona-engine/Containerfile.real",
        "infra/spire/federation/provisioner/Containerfile",
    ]
    assert len(group["digests"]) == 1


def test_rust_base_layer_has_seven_pin_sites(real_report: dict) -> None:
    """The seven Rust-CLI Containerfiles whose 14 placeholders were
    resolved on 2026-09-21. All seven must move together."""
    group = _group(real_report, "rust", "1.85-slim-bookworm")
    assert len(group["sites"]) == 7
    assert len(group["digests"]) == 1
    assert group["placeholder_tokens"] == []


def test_distroless_runtime_has_seven_pin_sites(real_report: dict) -> None:
    group = _group(real_report, "gcr.io/distroless/cc-debian12", "nonroot")
    assert len(group["sites"]) == 7
    assert len(group["digests"]) == 1
    assert group["placeholder_tokens"] == []


def test_no_rust_cli_containerfile_carries_a_placeholder(
    real_report: dict,
) -> None:
    """``DIGEST_PENDING_KAI_REVIEW`` is gone, not dated.

    ADR-0075 §3 gives undated exemptions teeth. The better outcome for
    an exemption whose blocker has dissolved is removal, and the blocker
    here had: both base images resolve. Re-introducing the token would
    mean the build resolves the digest in-runner again, which pins
    nothing.
    """
    for group in real_report["groups"]:
        assert "DIGEST_PENDING_KAI_REVIEW" not in group["placeholder_tokens"], (
            f"{group['image']}:{group['tag']} re-introduced the "
            f"DIGEST_PENDING_KAI_REVIEW placeholder"
        )
