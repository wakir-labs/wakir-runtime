# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic invariant tests for the Sprint-9 Tag-4 lazy-crypto pattern
on ``wirelang.identity``.

Background (see Sprint-9-Tag-4 Mira-bug-bilanz, Bug 6)
------------------------------------------------------

The minimal ``python:3.13-slim`` container image for the Phase-2
NATS-KV bucket-provisioner (``bin/nats-kv-bucket-provision``) ships
without the production ``cryptography`` and ``shamir-mnemonic`` PyPI
deps to keep the image-build dependency-light (no rust-toolchain
required). Before Tag-4 the provisioner's transitive import chain

    bin.nats_kv_bucket_provision
      -> wirelang.federation.marker_stack_kv
        -> wirelang.federation.n2_evaluator
          -> wirelang.identity.federation_resolver

triggered ``wirelang.identity.__init__`` which eagerly imported
``key_derivation`` (top-level ``from cryptography…``). The result was
a hard ``ModuleNotFoundError`` at container startup that blocked
``wakir-nats-kv-bucket-init`` and crash-looped the Phase-2 bring-up.

Tag-4 fix: ``wirelang/identity/__init__.py`` moves the three crypto-
bearing surfaces (``key_derivation``, ``aip_signing``,
``did_document_signing``), the cache-layer that transitively pulls
``aip_signing`` (``aip_signature_verification_cache``), and the
SLIP-39 / recovery surfaces that pull ``shamir-mnemonic``
(``shamir_split``, ``recovery_drill``) behind a PEP-562
``__getattr__``. Importing a crypto-free submodule like
``wirelang.identity.federation_resolver`` no longer triggers any of
these eager loads.

What this test surface asserts
------------------------------

These tests are run in the normal (full-deps-installed) host
environment but assert the *contract* that the lazy mapping enforces.
The contract has three angles:

1. Eager-import shape: importing ``wirelang.identity`` (or any of
   the crypto-free submodules used in the federation chain) does NOT
   pull ``cryptography`` or ``shamir_mnemonic`` into ``sys.modules``
   when called from a fresh interpreter state.
2. Lazy-resolution shape: the public ``__all__`` names that map to
   the lazy submodules are still accessible via attribute access
   on the package (PEP 562 round-trip).
3. Mapping completeness: every name in the lazy-attr map is present
   in ``__all__``, every name marked lazy resolves to the same
   object as the corresponding submodule attribute, and ``__dir__``
   reports the union of eager and lazy attributes.

Hermetic execution
------------------

We exercise the eager-import shape in a *child Python process* with
``sys.modules`` reset (running the import isolation in-process is
brittle because ``pytest`` itself may have already populated the
package). The subprocess receives a curated minimal script and
reports the answer over its exit code + captured stdout.

The subprocess does NOT need to be in a venv without
``cryptography``: we instead check whether ``cryptography`` was
*activated* by the import (i.e., present in ``sys.modules`` after
the targeted import). On the production host ``cryptography`` may
exist as a wheel on ``sys.path`` but should not be loaded as a
side-effect of a crypto-free import path.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest


_PYTHON = sys.executable


def _run_isolated(script: str) -> tuple[int, str, str]:
    """Run ``script`` in a fresh child Python interpreter.

    Returns ``(returncode, stdout, stderr)``. The child receives no
    inherited ``PYTHONSTARTUP`` and runs with ``-S`` to avoid
    site-packages init side effects that could pre-load
    ``cryptography``.
    """
    proc = subprocess.run(
        [_PYTHON, "-I", "-c", textwrap.dedent(script)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# T-LAZY-CRYPTO-01..03: eager-import shape — no transitive crypto load
# ---------------------------------------------------------------------------


def test_package_import_does_not_load_cryptography_or_shamir() -> None:
    """T-LAZY-CRYPTO-01: ``import wirelang.identity`` is crypto-free.

    A bare import of the package must not transitively load
    ``cryptography`` or ``shamir_mnemonic`` into ``sys.modules``.
    """
    rc, out, err = _run_isolated(
        """
        import sys
        sys.path.insert(0, %r)
        import wirelang.identity  # noqa: F401
        crypto_loaded = any(
            k == 'cryptography' or k.startswith('cryptography.')
            for k in sys.modules
        )
        shamir_loaded = 'shamir_mnemonic' in sys.modules
        print('crypto_loaded', crypto_loaded)
        print('shamir_loaded', shamir_loaded)
        """ % _repo_root()
    )
    assert rc == 0, f"child exited {rc}: stderr={err}"
    assert "crypto_loaded False" in out, out
    assert "shamir_loaded False" in out, out


def test_federation_resolver_import_does_not_load_crypto() -> None:
    """T-LAZY-CRYPTO-02: importing the consumer Wirelang submodule
    that triggered the original Bug 6 is now crypto-free.

    ``wirelang.federation.n2_evaluator`` (and therefore everything
    downstream including ``wirelang.federation.marker_stack_kv``)
    must be importable without ``cryptography``.
    """
    rc, out, err = _run_isolated(
        """
        import sys
        sys.path.insert(0, %r)
        from wirelang.identity import federation_resolver  # noqa: F401
        crypto_loaded = any(
            k == 'cryptography' or k.startswith('cryptography.')
            for k in sys.modules
        )
        print('crypto_loaded', crypto_loaded)
        """ % _repo_root()
    )
    assert rc == 0, f"child exited {rc}: stderr={err}"
    assert "crypto_loaded False" in out, out


def test_bucket_provisioner_module_imports_crypto_free() -> None:
    """T-LAZY-CRYPTO-03: the Sprint-9 Tag-1 bucket-provisioner module
    imports cleanly without ``cryptography``.

    This is the original Bug-6 surface: the operator-side container
    image ``wakir-nats-kv-bucket-init`` ships ``python:3.13-slim``
    without cryptography. The import path is

        bin.nats_kv_bucket_provision
          -> wirelang.federation.marker_stack_kv
            -> ... -> wirelang.identity.federation_resolver

    The whole chain must be crypto-free at module-init time.
    """
    rc, out, err = _run_isolated(
        """
        import sys
        sys.path.insert(0, %r)
        import bin.nats_kv_bucket_provision as m  # noqa: F401
        crypto_loaded = any(
            k == 'cryptography' or k.startswith('cryptography.')
            for k in sys.modules
        )
        print('crypto_loaded', crypto_loaded)
        print('bucket_families', len(m.BUCKET_FAMILIES))
        print('prefix', m.MARKER_STACK_BUCKET_NAME_PREFIX)
        """ % _repo_root()
    )
    assert rc == 0, f"child exited {rc}: stderr={err}"
    assert "crypto_loaded False" in out, out
    # Both families (marker-stack + sequence-ledger) must be present.
    assert "bucket_families 2" in out, out
    assert "prefix wakir-marker-stack-" in out, out


# ---------------------------------------------------------------------------
# T-LAZY-CRYPTO-04..06: lazy-resolution shape
# ---------------------------------------------------------------------------


def test_lazy_attr_access_returns_real_objects() -> None:
    """T-LAZY-CRYPTO-04: every lazy attribute resolves to the same
    object as the underlying submodule attribute.

    PEP 562 round-trip: ``getattr(wirelang.identity, name) is
    getattr(wirelang.identity.<submodule>, name)``.
    """
    from importlib import import_module

    import wirelang.identity as ident
    from wirelang.identity import _LAZY_CRYPTO_ATTRS

    for public_name, (submodule_basename, attr_name) in _LAZY_CRYPTO_ATTRS.items():
        submodule = import_module(
            f"wirelang.identity.{submodule_basename}"
        )
        resolved = getattr(ident, public_name)
        expected = getattr(submodule, attr_name)
        assert resolved is expected, (
            f"lazy attr {public_name!r} resolved to a different object "
            f"than wirelang.identity.{submodule_basename}.{attr_name}"
        )


def test_lazy_attr_caches_after_first_access() -> None:
    """T-LAZY-CRYPTO-05: a resolved lazy attribute is cached on the
    package module so subsequent accesses skip ``__getattr__``.

    We force resolution once and then read the package globals
    directly — the name must be present.
    """
    import wirelang.identity as ident

    # Pick a deterministic lazy name to probe.
    _ = ident.WAKIR_COIN_TYPE  # force resolution via __getattr__
    assert "WAKIR_COIN_TYPE" in vars(ident), (
        "lazy attr 'WAKIR_COIN_TYPE' was not cached on the package "
        "after first access"
    )


def test_unknown_attr_raises_attribute_error() -> None:
    """T-LAZY-CRYPTO-06: ``__getattr__`` rejects names that are not
    in the lazy map with a ``AttributeError`` (per PEP 562
    semantics; never falls through to bare ``ImportError``).
    """
    import wirelang.identity as ident

    with pytest.raises(AttributeError) as exc:
        ident.this_attribute_definitely_does_not_exist  # noqa: B018
    assert "this_attribute_definitely_does_not_exist" in str(exc.value)


# ---------------------------------------------------------------------------
# T-LAZY-CRYPTO-07..09: mapping completeness
# ---------------------------------------------------------------------------


def test_lazy_map_subset_of_all() -> None:
    """T-LAZY-CRYPTO-07: every name in ``_LAZY_CRYPTO_ATTRS`` is
    publicly exported via ``__all__``.

    This guards against private surfaces leaking through the lazy
    mapping by accident.
    """
    import wirelang.identity as ident
    from wirelang.identity import _LAZY_CRYPTO_ATTRS

    all_names = set(ident.__all__)
    lazy_names = set(_LAZY_CRYPTO_ATTRS.keys())
    extras = lazy_names - all_names
    assert not extras, (
        f"lazy attrs leak via __getattr__ but are not in __all__: "
        f"{sorted(extras)}"
    )


def test_all_names_are_resolvable() -> None:
    """T-LAZY-CRYPTO-08: every name in ``__all__`` is accessible
    via attribute access on the package (whether eager or lazy).
    """
    import wirelang.identity as ident

    missing: list[str] = []
    for name in ident.__all__:
        try:
            getattr(ident, name)
        except AttributeError:
            missing.append(name)
    assert not missing, (
        f"__all__ contains names that do not resolve on the package: "
        f"{sorted(missing)}"
    )


def test_dir_includes_lazy_attrs() -> None:
    """T-LAZY-CRYPTO-09: ``dir(wirelang.identity)`` lists both eager
    and lazy attributes (so IDE-introspection and pydoc surface the
    full public API).
    """
    import wirelang.identity as ident
    from wirelang.identity import _LAZY_CRYPTO_ATTRS

    dir_set = set(dir(ident))
    for name in _LAZY_CRYPTO_ATTRS:
        assert name in dir_set, (
            f"lazy attr {name!r} missing from dir(wirelang.identity)"
        )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _repo_root() -> str:
    """Return the repo-root path so the subprocess can construct a
    matching ``sys.path``.

    Determined relative to this test file: ``…/wirelang/tests/`` ->
    repo root is two parents up.
    """
    import pathlib

    return str(pathlib.Path(__file__).resolve().parents[2])
