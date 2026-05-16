# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Shared skip-marker for tests that exercise the V-907 pin-compute
path on a minimal-deps host.

Background (Sprint-Stability Tag-2, 2026-05-16)
-----------------------------------------------

The shadow-lane CI (``sandbox-suite-shadow`` in
``.github/workflows/tests.yml``) installs only the minimal dep set
``pytest + pytest-subtests + cryptography + shamir-mnemonic``. PyYAML
and rfc8785 are absent by design — the shadow lane is the
drift-detection sensor that catches *new* code paths quietly
acquiring a previously-optional dependency.

Tests in ``wirelang/tests/persona_engine/test_*.py`` that exercise
the actual V-907 pin-compute code path (``compute_v907_pin``,
``verify_v907_pin``, the engine-boot flow that calls
``verify_v907_pin`` transitively) require BOTH wheels:

- ``PyYAML``  — axis-A front-matter parsing.
- ``rfc8785`` — JCS canonicalisation for SHA-256.

The Sprint-Stability Tag-2 source-side fix lets
:mod:`wirelang.persona.persona_canonical_form` and
:mod:`wirelang.persona.persona_hash` load on a minimal-deps host
without exploding (try/except resolver pattern, parity with
:mod:`wirelang.identity.aip_signing`). The functions that actually
need the missing wheels raise
:class:`wirelang.persona.persona_canonical_form.PersonaCanonicalFormDependencyMissingError`
with an actionable install hint (``pip install
'wakir-runtime[persona]'``).

The engine-side caller (:func:`wirelang.persona_engine.v907_verify.compute_v907_pin`)
re-raises that as :class:`wirelang.persona_engine.v907_verify.PersonaHashComputeError`
with the same install-hint message — which is the substance
deliverable of Tag-2 (replaces the misleading pre-Tag-2 message
``"persona_canonical_form missing; this engine image is mis-built"``).

This module exposes a single :data:`requires_v907_compute_deps`
marker that the per-test decorators in the persona_engine test
suite attach to tests that exercise the compute path. Tests that
only touch persona-engine surfaces NOT in the compute path (config
parsing, despawn cleanup, format conformance, lifecycle state-machine
transitions, NATS-subscribe-loop wiring without a real
``compute_v907_pin`` call, …) continue to run in the shadow lane
unchanged.

Per-test (not module-level) skip granularity
--------------------------------------------

We deliberately use ``@pytest.mark.skipif`` per individual test
function rather than a module-level
``pytest.importorskip("rfc8785")`` for two reasons:

1. Several of the persona_engine modules contain a MIX of compute-
   touching and non-compute-touching tests. A module-level skip
   would lose shadow-lane coverage of the non-compute tests (e.g.
   the configuration-parsing happy-path tests in
   ``test_engine_and_cli.py``).

2. The drift-detection envelope in ``tests.yml drift-detection``
   compares ``--collect-only`` counts between production and
   sandbox lanes. Module-level ``importorskip`` zeros out the
   module's collected count in the lane that lacks the dep, which
   would shift the delta by ~152 tests (the total in the affected
   modules) and bust the ``EXPECTED_DELTA: '309'`` baseline
   (tolerance ±5). Per-test ``skipif`` preserves the collected
   count (tests are still collected; they skip at runtime), so the
   drift envelope stays exactly at the post-Tag-1 baseline.

Usage
-----

>>> from wirelang.tests.persona_engine._v907_compute_skip import (
...     requires_v907_compute_deps,
... )
>>>
>>> @requires_v907_compute_deps
>>> def test_compute_v907_pin_returns_sha256_prefix():
...     ...
"""

from __future__ import annotations

import importlib.util

import pytest


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


_HAS_YAML: bool = _has_module("yaml")
_HAS_RFC8785: bool = _has_module("rfc8785")
_HAS_V907_COMPUTE_DEPS: bool = _HAS_YAML and _HAS_RFC8785


#: Per-test decorator that skips when either ``PyYAML`` or ``rfc8785``
#: is absent from the environment.
#:
#: The reason-string includes the install hint that the source-side
#: :class:`PersonaCanonicalFormDependencyMissingError` also surfaces,
#: so a developer who hits the skip in their local environment gets
#: the same recovery guidance whether they read the test output or
#: the runtime exception.
requires_v907_compute_deps = pytest.mark.skipif(
    not _HAS_V907_COMPUTE_DEPS,
    reason=(
        "V-907 pin-compute requires PyYAML + rfc8785 "
        "(shadow-lane omits both by design). Install via "
        "`pip install 'wakir-runtime[persona]'` to enable."
    ),
)


__all__ = [
    "requires_v907_compute_deps",
    "_HAS_V907_COMPUTE_DEPS",
    "_HAS_YAML",
    "_HAS_RFC8785",
]
