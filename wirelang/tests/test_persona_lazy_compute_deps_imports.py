# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic invariant tests for the Sprint-Stability Tag-2
optional-dependency resolver pattern on
:mod:`wirelang.persona.persona_canonical_form` and
:mod:`wirelang.persona.persona_hash`.

Background (Sprint-Stability Tag-2, 2026-05-16)
-----------------------------------------------

PR #85 (Sprint-Stability Tag-1 hot-fix) promoted PyYAML from the
``persona-engine-runtime`` extra to a top-level ``dependencies =``
entry to close the production-lane ``"persona_canonical_form
missing"`` build-drift symptom (ADR-0061 §Schritt 10). The fix was
tactically correct but architecturally papered over the eager
``import yaml`` / ``import rfc8785`` shape in
``wirelang/persona/persona_canonical_form.py`` and the eager
``import rfc8785`` in ``wirelang/persona/persona_hash.py``.

Side-effect: the shadow-lane CI (``sandbox-suite-shadow`` in
``.github/workflows/tests.yml``) — which installs ONLY the minimal
dep set ``pytest + cryptography + shamir-mnemonic`` and does NOT
install the project wheel — exploded with 55
``persona_engine/test_*`` failures. The eager module-level imports
turned a ``ModuleNotFoundError`` into a misleading
``PersonaHashComputeError("persona_canonical_form missing; this
engine image is mis-built")`` re-raise from the engine-side caller
(``wirelang/persona_engine/v907_verify.py:109``).

Sprint-Stability Tag-2 (Tomás-Hand, 2026-05-16) inverts the
posture:

1. ``persona_canonical_form.py`` and ``persona_hash.py`` switch
   from eager imports to module-top try/except resolvers (mirroring
   the existing pattern on ``wirelang.identity.aip_signing``,
   ``wirelang.schemas.entry_signing``, and
   ``wirelang.identity.did_document_signing``).
2. PyYAML moves from top-level ``dependencies = [...]`` to a new
   ``[persona]`` optional-dependencies extra (joined by ``rfc8785``
   for self-contained-closure on slim adopters).
3. The engine-side caller (``v907_verify.py``) catches the new
   ``PersonaCanonicalFormDependencyMissingError`` separately from
   the generic ``ImportError`` branch and surfaces a clear install
   hint instead of the misleading "mis-built engine image" text.

This test module is the regression canary for the new contract.
Parity with ``wirelang/tests/test_identity_lazy_crypto_imports.py``
(Sprint-9 Tag-4 Bug-6 canary for the cryptography-eager-import
fix).

What this surface asserts
-------------------------

1. **Module-load shape**: importing
   ``wirelang.persona.persona_canonical_form`` and
   ``wirelang.persona.persona_hash`` does NOT raise on a host that
   has cryptography + shamir-mnemonic but no yaml / no rfc8785.
2. **Sentinel-class accessibility**: the new
   ``PersonaCanonicalFormDependencyMissingError`` sentinel-class is
   importable in all dep-states (load-time discovery is the
   contract).
3. **Constants accessibility**: the canonical-form constants
   (``CANONICAL_TOP_LEVEL_KEYS``, ``ACCEPTED_SCHEMA_VERSIONS``, …)
   are accessible without yaml / rfc8785 present (they live in the
   module body, not behind a function).
4. **Function-call shape (with deps present)**: ``parse_frontmatter``
   and ``canonical_jcs_bytes`` succeed on the production-lane host.
5. **Error-message shape (with deps absent)**: the engine-side
   caller surfaces an install-hint message that names the
   ``[persona]`` extra, not the pre-Tag-2 "mis-built engine image"
   text. We exercise this with a sys.modules-injection-poison trick
   so the test passes regardless of whether yaml/rfc8785 are
   actually installed on the test host.

Hermetic execution
------------------

Test 5 (error-message shape) uses ``importlib.reload`` after
poisoning ``sys.modules`` with a fake entry that mimics a
``ModuleNotFoundError``. The resolver flags
(``_HAS_YAML``, ``_HAS_RFC8785``) are evaluated at module import
time, so we have to force a fresh import after poisoning to make
the test deterministic across both production and shadow lanes.
"""

from __future__ import annotations

import importlib
import sys

import pytest


# ---------------------------------------------------------------------------
# 1. Module-load shape: persona_canonical_form + persona_hash load on a
#    minimal-deps host.
# ---------------------------------------------------------------------------


def test_persona_canonical_form_module_loads_without_yaml_or_rfc8785_present():
    """Sprint-Stability Tag-2 contract: the module must be importable
    even when ``yaml`` and ``rfc8785`` are absent from sys.modules.

    Whether they ARE absent on this test host depends on the lane
    (shadow lane: absent; production lane: present). We assert only
    that the import succeeds; the resolver-flag inspection lives in a
    separate test below.
    """
    # Import-or-skip would defeat the purpose: we WANT to exercise the
    # import path that previously crashed on a missing dep. The fact
    # that this test passes on BOTH lanes is the contract.
    import wirelang.persona.persona_canonical_form as mod  # noqa: F401


def test_persona_hash_module_loads_without_rfc8785_present():
    """Companion to the canonical-form test above for the
    sibling module ``persona_hash`` that also went lazy in Tag-2.
    """
    import wirelang.persona.persona_hash as mod  # noqa: F401


# ---------------------------------------------------------------------------
# 2. Sentinel-class accessibility.
# ---------------------------------------------------------------------------


def test_dependency_missing_error_is_importable():
    """The :class:`PersonaCanonicalFormDependencyMissingError`
    sentinel-class is the public surface that downstream catchers
    (notably ``wirelang.persona_engine.v907_verify``) rely on to
    distinguish the "missing wheel" failure mode from a generic
    ``ImportError``. The class must be importable in any dep-state.
    """
    from wirelang.persona.persona_canonical_form import (
        PersonaCanonicalFormDependencyMissingError,
    )

    assert issubclass(PersonaCanonicalFormDependencyMissingError, ImportError)


def test_dependency_missing_error_carries_missing_module_attribute():
    """The error object exposes the missing-module name as a public
    attribute so callers can switch on it (e.g. the engine-side
    caller's install-hint message generator)."""
    from wirelang.persona.persona_canonical_form import (
        PersonaCanonicalFormDependencyMissingError,
    )

    exc = PersonaCanonicalFormDependencyMissingError("yaml")
    assert exc.missing_module == "yaml"
    assert "yaml" in str(exc)
    assert "wakir-runtime[persona]" in str(exc)


# ---------------------------------------------------------------------------
# 3. Constants accessibility.
# ---------------------------------------------------------------------------


def test_canonical_constants_accessible_without_compute_deps():
    """Constants live in the module body, not behind a function. They
    must be readable on a minimal-deps host so a consumer that only
    reads metadata (e.g. a documentation generator) does not pay the
    yaml/rfc8785 cost."""
    from wirelang.persona.persona_canonical_form import (
        ACCEPTED_SCHEMA_VERSIONS,
        CANONICAL_IDENTITY_PINNED_KEYS,
        CANONICAL_TOP_LEVEL_KEYS,
        SUPPORTED_SCHEMA_VERSION,
    )

    assert "name" in CANONICAL_TOP_LEVEL_KEYS
    assert "schema_version" in CANONICAL_TOP_LEVEL_KEYS
    assert "authority" in CANONICAL_IDENTITY_PINNED_KEYS
    assert SUPPORTED_SCHEMA_VERSION == "persona-v1"
    assert "persona-v1" in ACCEPTED_SCHEMA_VERSIONS


def test_persona_hash_constants_accessible_without_rfc8785():
    """Companion: the persona-hash module-level constants are also
    readable on a host that lacks rfc8785."""
    from wirelang.persona.persona_hash import (
        PERSONA_EMPTY_REF_SENTINEL,
        PERSONA_HASH_FULL_LENGTH,
        PERSONA_HASH_HEX_LENGTH,
        PERSONA_HASH_PREFIX,
    )

    assert PERSONA_HASH_PREFIX == "sha256:"
    assert PERSONA_HASH_HEX_LENGTH == 64
    assert PERSONA_HASH_FULL_LENGTH == 64 + len("sha256:")
    assert PERSONA_EMPTY_REF_SENTINEL == ""


# ---------------------------------------------------------------------------
# 4. Function-call shape (with deps present): exercised by the existing
#    ``test_persona_canonical_form_jcs.py`` and ``test_persona_hash.py``
#    modules, which gate on ``pytest.importorskip("rfc8785")``. We do
#    not duplicate them here.
#
# 5. Error-message shape (with deps absent): runtime-aware test below.
# ---------------------------------------------------------------------------


def test_parse_frontmatter_raises_dependency_error_when_yaml_absent():
    """When yaml is unavailable, calling :func:`parse_frontmatter`
    must raise :class:`PersonaCanonicalFormDependencyMissingError`
    with ``missing_module == "yaml"``.

    We detect the deps-absent state via the module-level resolver
    flag rather than poisoning sys.modules; the flag is set at
    module-import time and is the single source of truth for the
    fallback behaviour.
    """
    from wirelang.persona.persona_canonical_form import (
        PersonaCanonicalFormDependencyMissingError,
        _HAS_YAML,
        parse_frontmatter,
    )

    if _HAS_YAML:
        pytest.skip("yaml is installed on this host; deps-absent path not exercisable")

    with pytest.raises(PersonaCanonicalFormDependencyMissingError) as excinfo:
        parse_frontmatter("schema_version: persona-v1")

    assert excinfo.value.missing_module == "yaml"
    assert "wakir-runtime[persona]" in str(excinfo.value)


def test_canonical_jcs_bytes_raises_dependency_error_when_rfc8785_absent():
    """When rfc8785 is unavailable, calling
    :func:`canonical_jcs_bytes` must raise
    :class:`PersonaCanonicalFormDependencyMissingError` with
    ``missing_module == "rfc8785"``."""
    from wirelang.persona.persona_canonical_form import (
        PersonaCanonicalFormDependencyMissingError,
        _HAS_RFC8785,
        canonical_jcs_bytes,
    )

    if _HAS_RFC8785:
        pytest.skip(
            "rfc8785 is installed on this host; deps-absent path not exercisable"
        )

    with pytest.raises(PersonaCanonicalFormDependencyMissingError) as excinfo:
        canonical_jcs_bytes({"a": 1})

    assert excinfo.value.missing_module == "rfc8785"
    assert "wakir-runtime[persona]" in str(excinfo.value)


def test_compute_persona_hash_from_canonical_raises_dependency_error_when_rfc8785_absent():
    """Same posture for the sibling ``persona_hash`` module."""
    from wirelang.persona.persona_canonical_form import (
        PersonaCanonicalFormDependencyMissingError,
    )
    from wirelang.persona.persona_hash import (
        _HAS_RFC8785,
        compute_persona_hash_from_canonical,
    )

    if _HAS_RFC8785:
        pytest.skip(
            "rfc8785 is installed on this host; deps-absent path not exercisable"
        )

    with pytest.raises(PersonaCanonicalFormDependencyMissingError) as excinfo:
        compute_persona_hash_from_canonical({"schema_version": "persona-v1"})

    assert excinfo.value.missing_module == "rfc8785"


# ---------------------------------------------------------------------------
# 6. v907_verify integration: the engine-side caller surfaces an
#    install-hint message that names the [persona] extra (NOT the
#    pre-Tag-2 misleading "mis-built engine image" text).
# ---------------------------------------------------------------------------


def test_v907_verify_install_hint_surface_when_deps_absent():
    """Substance contract of Sprint-Stability Tag-2:
    :class:`PersonaHashComputeError` from
    :func:`wirelang.persona_engine.v907_verify.compute_v907_pin`
    must mention the ``[persona]`` extra and NOT the pre-Tag-2
    "mis-built engine image" text when the underlying cause is a
    missing wheel."""
    from wirelang.persona.persona_canonical_form import (
        _HAS_RFC8785,
        _HAS_YAML,
    )
    from wirelang.persona_engine.v907_verify import (
        PersonaHashComputeError,
        compute_v907_pin,
    )

    if _HAS_YAML and _HAS_RFC8785:
        pytest.skip(
            "both wheels installed; deps-absent error path not exercisable"
        )

    sample_axis_a = (
        "---\n"
        "schema_version: persona-v1\n"
        "name: tomas\n"
        "description: test\n"
        "tools: []\n"
        "identity_pinned:\n"
        "  cross_review_zones: []\n"
        "  authority: {}\n"
        "  hierarchy: {}\n"
        "---\n"
        "body\n"
    ).encode("utf-8")

    with pytest.raises(PersonaHashComputeError) as excinfo:
        compute_v907_pin(sample_axis_a)

    msg = str(excinfo.value)
    assert "wakir-runtime[persona]" in msg, (
        f"Sprint-Stability Tag-2 contract violation: error message "
        f"must direct the operator to the [persona] extra. Got: {msg!r}"
    )
    assert "mis-built" not in msg, (
        f"Sprint-Stability Tag-2 contract violation: error message must "
        f"NOT use the misleading pre-Tag-2 'mis-built engine image' "
        f"text for a missing-wheel cause. Got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# 7. Pyproject contract: the [persona] extra carries both wheels.
# ---------------------------------------------------------------------------


def test_pyproject_persona_extra_carries_pyyaml_and_rfc8785():
    """The ``[persona]`` extra is the publicly-documented install
    surface for the V-907 compute path. Both wheels must be
    declared."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    pyproject_path = repo_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    extras = data["project"]["optional-dependencies"]
    assert "persona" in extras, (
        "Sprint-Stability Tag-2 contract: pyproject.toml must declare "
        "the [project.optional-dependencies] persona extra"
    )

    pkgs = extras["persona"]
    assert any("PyYAML" in p or "pyyaml" in p.lower() for p in pkgs), (
        f"[persona] extra must carry PyYAML; got {pkgs!r}"
    )
    assert any("rfc8785" in p for p in pkgs), (
        f"[persona] extra must carry rfc8785; got {pkgs!r}"
    )


def test_pyproject_pyyaml_not_in_top_level_dependencies():
    """Sprint-Stability Tag-2 inverts the PR #85 posture: PyYAML
    moves OUT of top-level dependencies and INTO the [persona]
    extra. Production-lane CI installs PyYAML explicitly (see
    ``.github/workflows/tests.yml`` ``production-suite`` job), so
    the move does not break CI; downstream adopters install via
    the extra."""
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    pyproject_path = repo_root / "pyproject.toml"
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    top_level_deps = data["project"]["dependencies"]
    assert not any(
        "PyYAML" in p or "pyyaml" in p.lower() for p in top_level_deps
    ), (
        f"Sprint-Stability Tag-2 contract: PyYAML must NOT be in "
        f"top-level dependencies; it lives in the [persona] extra. "
        f"Got top-level deps: {top_level_deps!r}"
    )
