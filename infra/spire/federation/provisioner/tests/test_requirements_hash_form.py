# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""Hermetic hash-pin form invariants for the wakir-provisioner image's
build-input requirements file (Phase-2 Sprint-9 Tag-4).

The Containerfile installs the runtime wheel set with
``pip install --require-hashes -r requirements.txt``. After Reza-PR
#33 (Wirelang-Import-Disentanglement, PEP-562 lazy ``__getattr__`` on
``wirelang.federation``), the v0.1.1 image's wheel set shrinks to a
single wheel — ``nats-py`` only. The v0.1.0 image carried three
additional transitive-import-satisfying wheels (``cryptography``,
``rfc8785``, ``jsonschema``); they no longer fire on the provisioner's
code paths and the v0.1.1 image drops them. This test suite asserts
the on-disk SYNTAX of the requirements file without ever invoking
pip / network resolvers:

  * Every pinned package MUST use a ``==<version>`` strict pin.
  * Every package MUST carry at least one ``--hash=sha256:<value>``
    continuation, where ``<value>`` is EITHER the placeholder token
    ``HASH_PENDING_TOMAS_REVIEW`` OR a canonical 64-hex sha256.
  * The exact one package (``nats-py``) is present and named exactly
    once.
  * The pin version for ``nats-py`` matches the version in the
    sibling top-level ``requirements-nats.txt`` (the bind-mounted
    host runtime tests against the same nats-py version as the
    image; a mismatch would let the live integration drift silently
    against the hermetic test surface).

Sandbox boundary: this test reads files on disk only. Live PyPI
hash resolution stays Operator-Hand per
``feedback_sandbox_host_trennung.md``; one-shot read-only WebFetch
of the PyPI JSON API for canonical sha256 lookup is permitted as a
trusted external source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
REQUIREMENTS = (
    REPO_ROOT
    / "infra"
    / "spire"
    / "federation"
    / "provisioner"
    / "requirements.txt"
)
TOP_LEVEL_NATS_REQUIREMENTS = REPO_ROOT / "requirements-nats.txt"

PLACEHOLDER = "HASH_PENDING_TOMAS_REVIEW"

EXPECTED_PACKAGES = ("nats-py",)


# Matches a ``<pkg>==<version>`` line (the actual pin), possibly with a
# trailing backslash continuation. Whitespace tolerated.
_PIN_LINE_RE = re.compile(
    r"^(?P<pkg>[A-Za-z0-9_.\-]+)==(?P<version>[A-Za-z0-9_.\-+]+)"
    r"(?:\s+\\)?\s*$",
    re.MULTILINE,
)
_HASH_LINE_RE = re.compile(
    r"--hash=sha256:(?P<value>[A-Za-z0-9_]+)"
)


def _read(path: Path) -> str:
    assert path.exists(), f"required file missing: {path}"
    return path.read_text(encoding="utf-8")


def test_requirements_file_exists() -> None:
    assert REQUIREMENTS.exists(), (
        f"missing wakir-provisioner requirements file: {REQUIREMENTS}"
    )


def test_every_expected_package_is_pinned_exactly_once() -> None:
    """The runtime wheel set (v0.1.1: ``nats-py`` only, post Reza-PR
    #33) MUST be pinned exactly once each. A duplicate pin (e.g. two
    ``nats-py==...`` lines) indicates a bump or rebase mistake. The
    inverted assertion (extras-set is empty) also rejects accidental
    re-introduction of the v0.1.0 transitive-import wheels
    (``cryptography``, ``rfc8785``, ``jsonschema``) — adding them
    back is allowed but must update :data:`EXPECTED_PACKAGES` first."""
    text = _read(REQUIREMENTS)
    pinned_packages: list[str] = []
    for match in _PIN_LINE_RE.finditer(text):
        pinned_packages.append(match.group("pkg"))
    for pkg in EXPECTED_PACKAGES:
        count = sum(1 for p in pinned_packages if p == pkg)
        assert count == 1, (
            f"expected exactly one pin line for {pkg!r}; found {count} "
            f"(all pins: {pinned_packages})"
        )
    # Exactly the expected packages, no extras.
    extras = set(pinned_packages) - set(EXPECTED_PACKAGES)
    assert not extras, (
        f"unexpected packages in requirements.txt: {extras}; the "
        f"runtime wheel set is intentionally minimal "
        f"({EXPECTED_PACKAGES})"
    )


def test_every_pin_uses_strict_equality() -> None:
    """``--require-hashes`` only works with strict ``==`` pins;
    range pins (``>=``, ``~=``) are silently incompatible."""
    text = _read(REQUIREMENTS)
    # Look for any range operators on a pinned-package line.
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#") or not line:
            continue
        # Skip --hash continuation lines.
        if line.startswith("--hash"):
            continue
        # Skip lone backslash continuation lines.
        if line == "\\":
            continue
        # The first token before any whitespace should match
        # <pkg>==<version> exactly. Bad operators: >=, <=, ~=, !=
        first_token = line.split()[0]
        for bad_op in (">=", "<=", "~=", "!=", ">", "<"):
            assert bad_op not in first_token, (
                f"non-strict pin operator {bad_op!r} found in line: "
                f"{raw!r}; --require-hashes needs == pins"
            )


def test_every_pin_carries_at_least_one_hash() -> None:
    """Each pinned package MUST carry at least one
    ``--hash=sha256:<value>`` continuation. Pip's
    ``--require-hashes`` refuses to install a pin without a hash."""
    text = _read(REQUIREMENTS)
    # Naive but adequate: split into pin-stanzas separated by blank
    # lines, and check each stanza has at least one ``--hash=``.
    stanzas: list[str] = []
    current: list[str] = []
    for raw in text.splitlines():
        if raw.strip().startswith("#"):
            continue
        if not raw.strip():
            if current:
                stanzas.append("\n".join(current))
                current = []
            continue
        current.append(raw)
    if current:
        stanzas.append("\n".join(current))

    pin_stanzas = [s for s in stanzas if _PIN_LINE_RE.search(s)]
    assert pin_stanzas, "no pin stanzas found in requirements.txt"
    for stanza in pin_stanzas:
        # Identify which package this stanza pins (for error
        # messages).
        pin_match = _PIN_LINE_RE.search(stanza)
        pkg = pin_match.group("pkg") if pin_match else "<unknown>"
        hashes = _HASH_LINE_RE.findall(stanza)
        assert hashes, (
            f"pin stanza for {pkg!r} carries no --hash= continuation; "
            f"--require-hashes will fail at install time"
        )


def test_every_hash_value_is_placeholder_or_64_hex() -> None:
    """The ``--hash=sha256:<value>`` slot MUST be either the
    placeholder token or a canonical 64-hex sha256. A half-resolved
    state (one package real, others placeholder) is an invariant
    breach: the build either resolves ALL hashes or NONE."""
    text = _read(REQUIREMENTS)
    values = [m.group("value") for m in _HASH_LINE_RE.finditer(text)]
    assert values, "no --hash=sha256: continuations found"
    real_count = 0
    placeholder_count = 0
    for v in values:
        if v == PLACEHOLDER:
            placeholder_count += 1
        elif re.fullmatch(r"[a-f0-9]{64}", v):
            real_count += 1
        else:
            pytest.fail(
                f"non-canonical hash value: {v!r}; must be "
                f"{PLACEHOLDER} or 64-hex sha256"
            )
    # All-or-nothing: either every line is the placeholder, or every
    # line is a real digest. Half-resolved state is an invariant
    # breach (an Operator-Hand resolution step was interrupted).
    if real_count > 0 and placeholder_count > 0:
        pytest.fail(
            f"half-resolved hash state: {real_count} real digests + "
            f"{placeholder_count} placeholders; finish the resolution "
            f"or revert to all-placeholder"
        )


def test_nats_py_version_matches_top_level_requirements_nats_txt() -> None:
    """The ``nats-py`` version pinned here MUST match the version
    pinned in the top-level ``requirements-nats.txt`` (the
    bind-mounted host runtime tests against the same version as the
    image; a mismatch lets the live integration drift silently
    against the hermetic test surface)."""
    if not TOP_LEVEL_NATS_REQUIREMENTS.exists():
        pytest.skip(
            f"sibling file not present: {TOP_LEVEL_NATS_REQUIREMENTS}"
        )
    image_text = _read(REQUIREMENTS)
    top_text = _read(TOP_LEVEL_NATS_REQUIREMENTS)

    def _nats_version(text: str) -> str | None:
        for match in _PIN_LINE_RE.finditer(text):
            if match.group("pkg") == "nats-py":
                return match.group("version")
        return None

    image_v = _nats_version(image_text)
    top_v = _nats_version(top_text)
    assert image_v is not None, (
        "provisioner requirements.txt does not pin nats-py"
    )
    assert top_v is not None, (
        "top-level requirements-nats.txt does not pin nats-py"
    )
    assert image_v == top_v, (
        f"nats-py version drift: provisioner image pins {image_v!r}, "
        f"top-level requirements-nats.txt pins {top_v!r}; the two "
        f"must agree byte-precisely (Cross-Review Zone-B paired-"
        f"update on bump)"
    )
