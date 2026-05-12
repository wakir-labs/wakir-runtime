# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
#
# Hermetic tests for the nats-py manifest pin (Phase-2 Sprint-5 Tag-5,
# Option G / OI-5 dependency-hygiene solo-box).
#
# Test plan (hermetic — no network, no PyPI hit, no pip invoke):
#
#   1. ``pyproject.toml`` has a ``nats`` optional-dependency group
#      pinning ``nats-py==2.14.0`` byte-precise.
#   2. ``requirements-nats.txt`` exists and pins ``nats-py==2.14.0``
#      with both the wheel and sdist sha256 hashes byte-precise.
#   3. The hashes in ``requirements-nats.txt`` are exactly the two
#      48-char hex strings recorded as the Sprint-4-Tag-2 first-time
#      live-smoke validated PyPI payload (cross-verified via the PyPI
#      JSON metadata endpoint on 2026-05-11 and two independent local
#      hashing tools on the wheel/sdist payload).
#   4. ``pyproject.toml`` and ``requirements-nats.txt`` agree on the
#      pinned version string (no version-drift between the two
#      surfaces).
#
# Why hermetic?
# -------------
# The pin-stability gate is a static-file invariant: if the two
# manifest surfaces ever drift apart (or the recorded hashes ever
# silently change), the install path on a fresh build host is no
# longer reproducible. Catching that drift requires only file-content
# inspection — no network, no pip resolver, no installed nats-py.
#
# A live-install smoke (``pip install --require-hashes -r
# requirements-nats.txt`` on a Bluefin/Silverblue build host against
# the live PyPI index) is an operator-hand follow-up, not a hermetic
# pytest unit. It is captured as OI-5-live in Sprint-5-Tag-5 outbox.

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYPROJECT = REPO_ROOT / "pyproject.toml"
REQUIREMENTS = REPO_ROOT / "requirements-nats.txt"

# Byte-precise expected pin values for this Sprint-5-Tag-5 anchor.
# Drift in either surface is caught by the cross-check test below.
EXPECTED_VERSION = "2.14.0"
EXPECTED_WHEEL_HASH = (
    "4116f5d2233ce16e63c3d5538fa40a5e207f75fcf42a741773929ddf1e29d19d"
)
EXPECTED_SDIST_HASH = (
    "4ed02cb8e3b55c68074a063aa2687087115d805d1513297da90cb2068fb07bed"
)


def _read_pyproject() -> dict:
    """Load ``pyproject.toml`` as parsed TOML (stdlib tomllib)."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


def test_pyproject_pins_nats_py_exactly() -> None:
    """Test 1 — ``pyproject.toml`` pins ``nats-py==2.14.0`` byte-precise.

    The ``nats`` optional-dependency group must exist, and its single
    entry must be the exact-version pin (``==``, not ``>=``, not
    ``~=``). A loose pin would let a fresh build host install a
    newer-than-validated wheel and silently drift away from the
    Sprint-4-Tag-2 first-time live-smoke baseline.
    """
    data = _read_pyproject()
    opt = data["project"]["optional-dependencies"]
    assert "nats" in opt, (
        "pyproject.toml is missing the 'nats' optional-dependency "
        "group; OI-5 manifest-pin is not in place"
    )
    pins = opt["nats"]
    assert pins == [f"nats-py=={EXPECTED_VERSION}"], (
        f"expected pyproject [project.optional-dependencies] nats "
        f"to equal ['nats-py=={EXPECTED_VERSION}'], got {pins!r}"
    )


def test_requirements_nats_pins_wheel_and_sdist_hashes() -> None:
    """Test 2 — ``requirements-nats.txt`` carries both sha256 hashes.

    The hash-pinned constraints file is the canonical install path
    for build hosts (``pip install --require-hashes -r ...``). Both
    the wheel-sha256 and the sdist-sha256 must appear, so an offline
    or sdist-only install path still satisfies ``--require-hashes``.
    """
    assert REQUIREMENTS.exists(), (
        "requirements-nats.txt is missing; OI-5 hash-pin install "
        "path is not in place"
    )
    body = REQUIREMENTS.read_text(encoding="utf-8")
    # Drop comments + blank lines for a clean install-spec view.
    install_lines = [
        line for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    install_spec = "\n".join(install_lines)
    # Version pin must appear exactly once.
    assert f"nats-py=={EXPECTED_VERSION}" in install_spec, (
        f"requirements-nats.txt does not contain the exact pin "
        f"'nats-py=={EXPECTED_VERSION}'; version-pin drift"
    )
    # Both hashes must appear; order is irrelevant to pip --require-hashes.
    assert EXPECTED_WHEEL_HASH in install_spec, (
        f"requirements-nats.txt is missing the wheel sha256 "
        f"{EXPECTED_WHEEL_HASH!r}; OI-5 hash-pin payload drift"
    )
    assert EXPECTED_SDIST_HASH in install_spec, (
        f"requirements-nats.txt is missing the sdist sha256 "
        f"{EXPECTED_SDIST_HASH!r}; OI-5 hash-pin payload drift"
    )


def test_hash_format_is_canonical_sha256() -> None:
    """Test 3 — Each ``--hash=sha256:`` token is the canonical form.

    pip's ``--require-hashes`` mode accepts hex-lowercase 64-char
    sha256 digests. A drift to upper-case, truncation, or trailing
    whitespace would silently weaken the supply-chain gate. This
    test pins the canonical-form invariant for both hashes.
    """
    body = REQUIREMENTS.read_text(encoding="utf-8")
    pattern = re.compile(r"--hash=sha256:([0-9a-f]{64})")
    matches = pattern.findall(body)
    # We expect exactly two hash lines (wheel + sdist) and nothing more.
    assert len(matches) == 2, (
        f"expected exactly 2 sha256 hash tokens in canonical form "
        f"(64-char hex-lowercase), got {len(matches)}: {matches!r}"
    )
    # The set must equal the Sprint-4-Tag-2 first-time-validated pair.
    assert set(matches) == {EXPECTED_WHEEL_HASH, EXPECTED_SDIST_HASH}, (
        f"hash-set drift in requirements-nats.txt; expected "
        f"{{{EXPECTED_WHEEL_HASH!r}, {EXPECTED_SDIST_HASH!r}}}, "
        f"got {set(matches)!r}"
    )


def test_pyproject_and_requirements_agree_on_version() -> None:
    """Test 4 — Cross-surface version-pin agreement.

    ``pyproject.toml`` (project-metadata, library-consumer-facing) and
    ``requirements-nats.txt`` (operator-hand build-host install path)
    are two manifest surfaces for the same dependency. They MUST
    agree on the version string at commit time; a drift means one of
    the two install paths will go off-baseline silently.
    """
    data = _read_pyproject()
    pins = data["project"]["optional-dependencies"]["nats"]
    pyproject_pin = pins[0]  # 'nats-py==2.14.0'

    body = REQUIREMENTS.read_text(encoding="utf-8")
    # The first install-spec line in requirements-nats.txt starts with
    # the canonical pin form 'nats-py==<version>'; pull the version
    # off it for a byte-precise cross-compare.
    pin_pattern = re.compile(r"^\s*(nats-py==[\d.]+)", re.MULTILINE)
    match = pin_pattern.search(body)
    assert match is not None, (
        "requirements-nats.txt has no parseable 'nats-py==<version>' "
        "install spec; cross-surface pin compare cannot run"
    )
    requirements_pin = match.group(1)

    assert pyproject_pin == requirements_pin, (
        f"cross-surface version-pin drift: pyproject says "
        f"{pyproject_pin!r}, requirements-nats.txt says "
        f"{requirements_pin!r}; OI-5 invariant violated"
    )
