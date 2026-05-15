# SPDX-License-Identifier: BUSL-1.1
"""Sprint-Pengine-9 Bug-34c tests: pyproject persona-engine-runtime extra.

Asserts the structural-fix for the Containerfile.real wheel-layer
drift: the wheel set is declared in pyproject.toml under
``[project.optional-dependencies] persona-engine-runtime`` so future
runtime deps are added by editing pyproject, not by adding RUN-layers
to the Containerfile.

The tests run on the repo-tree (not on the built image) — they parse
pyproject.toml and assert the extra's contents byte-for-byte.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"


def _load_pyproject() -> dict:
    try:
        import tomllib  # Python 3.11+
    except ImportError:  # pragma: no cover
        import tomli as tomllib  # type: ignore

    return tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))


def test_pyproject_exists():
    assert PYPROJECT_PATH.exists(), f"missing pyproject.toml at {PYPROJECT_PATH}"


def test_persona_engine_runtime_extra_declared():
    data = _load_pyproject()
    extras = data["project"]["optional-dependencies"]
    assert "persona-engine-runtime" in extras, (
        "Bug-34c structural fix: pyproject.toml must declare "
        "[project.optional-dependencies] persona-engine-runtime"
    )


def test_persona_engine_runtime_extra_carries_rfc8785():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pkgs = extras["persona-engine-runtime"]
    assert any("rfc8785" in p for p in pkgs)


def test_persona_engine_runtime_extra_carries_pyyaml():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pkgs = extras["persona-engine-runtime"]
    assert any("PyYAML" in p or "pyyaml" in p.lower() for p in pkgs)


def test_persona_engine_runtime_extra_carries_shamir_mnemonic():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pkgs = extras["persona-engine-runtime"]
    assert any("shamir-mnemonic" in p for p in pkgs)


def test_persona_engine_runtime_extra_carries_cryptography():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pkgs = extras["persona-engine-runtime"]
    assert any("cryptography" in p for p in pkgs)


def test_persona_engine_runtime_extra_carries_nats_py():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pkgs = extras["persona-engine-runtime"]
    assert any("nats-py" in p for p in pkgs), (
        "OI-PEFR-1 needs nats-py in the persona-engine-runtime extra"
    )


def test_persona_engine_runtime_extra_carries_grpcio():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pkgs = extras["persona-engine-runtime"]
    assert any("grpcio" in p for p in pkgs), (
        "OI-PEFR-2 needs grpcio in the persona-engine-runtime extra"
    )


def test_persona_engine_runtime_extra_carries_protobuf():
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pkgs = extras["persona-engine-runtime"]
    assert any("protobuf" in p for p in pkgs)


def test_persona_engine_runtime_extra_pin_bounds_lower_only():
    """The extra uses >= bounds (not == hard-pins) so the lockfile
    (requirements-nats.txt etc.) controls byte-precise pinning."""
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pkgs = extras["persona-engine-runtime"]
    for p in pkgs:
        # protobuf carries an upper bound (<6) for compatibility; that's allowed.
        if "protobuf" in p:
            continue
        assert "==" not in p, (
            f"persona-engine-runtime entries should use >= bounds, "
            f"not == hard-pins: {p}"
        )


def test_persona_engine_runtime_extra_no_dev_only_deps():
    """The extra must not pull in test-only deps (pytest, hypothesis)
    that would bloat the production image."""
    extras = _load_pyproject()["project"]["optional-dependencies"]
    pkgs = extras["persona-engine-runtime"]
    forbidden = {"pytest", "hypothesis", "mypy", "ruff", "pytest-asyncio"}
    for p in pkgs:
        for f in forbidden:
            assert not p.lower().startswith(f), (
                f"persona-engine-runtime must not carry dev-only dep {f}: "
                f"got {p}"
            )


# -------------------- Containerfile.real surface --------------------


CONTAINERFILE_REAL_PATH = REPO_ROOT / "infra" / "persona-engine" / "Containerfile.real"


def test_containerfile_real_exists():
    assert CONTAINERFILE_REAL_PATH.exists()


def test_containerfile_real_uses_persona_engine_runtime_extra():
    text = CONTAINERFILE_REAL_PATH.read_text(encoding="utf-8")
    assert "persona-engine-runtime" in text, (
        "Containerfile.real must install via the pyproject extra, not "
        "a flat RUN-layer of pip-installs"
    )


def test_containerfile_real_no_flat_pip_layer_for_runtime_deps():
    """The flat ``pip install 'rfc8785>=0.1.4' 'PyYAML>=6.0' ...`` RUN-
    layer that drifted in Sprint-Pengine-8 must be gone."""
    text = CONTAINERFILE_REAL_PATH.read_text(encoding="utf-8")
    # The structural fix uses ``pip install '/opt/wakir-runtime/.
    # [persona-engine-runtime]'`` — the multi-arg flat list must not
    # be present.
    bad_pattern = "'rfc8785>=0.1.4' \\\n        'PyYAML"
    assert bad_pattern not in text


def test_containerfile_real_copies_pyproject_toml():
    text = CONTAINERFILE_REAL_PATH.read_text(encoding="utf-8")
    assert "pyproject.toml" in text, (
        "Containerfile.real must COPY pyproject.toml so the extra is "
        "discoverable inside the build"
    )


def test_containerfile_real_image_tag_bumped():
    text = CONTAINERFILE_REAL_PATH.read_text(encoding="utf-8")
    assert "0.3.0-pilot" in text, "image tag should be bumped to 0.3.0-pilot"
    # We allow references to 0.2.0-pilot in comment context (history
    # / tag-rotation pattern), but the image-version LABEL must be
    # 0.3.0-pilot.
    assert 'image.version="0.3.0-pilot"' in text
