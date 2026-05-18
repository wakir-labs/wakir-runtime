# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Asyncio-marker conftest for the persona-engine in-tree tests.

This sibling-conftest mirrors the pure-stdlib asyncio-runner pattern
established in ``wirelang/tests/conftest.py``. The hook is duplicated
(not imported) because the two conftests live on different pytest-
discovery branches: ``wirelang/tests/conftest.py`` does not apply to
test files under ``wirelang/persona_engine/tests/``.

Rationale (Tag-46): the Tag-46 Selin auftrag named
``wirelang/persona_engine/tests/test_nats_jetstream_loss_recovery_a8.py``
as the file path. Adding the asyncio-runner here keeps the auftrag's
path-anchor stable while preserving the pure-stdlib posture (no
pytest-asyncio dependency).
"""

from __future__ import annotations

import asyncio
import inspect

import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "asyncio: run the test coroutine with asyncio.run "
        "(Tag-46 A8 hermetic JetStream-loss tests).",
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_pyfunc_call(pyfuncitem):
    """Drive ``@pytest.mark.asyncio`` test coroutines via asyncio.run."""
    marker = pyfuncitem.get_closest_marker("asyncio")
    if marker is not None and inspect.iscoroutinefunction(pyfuncitem.obj):
        funcargs = pyfuncitem.funcargs
        argnames = pyfuncitem._fixtureinfo.argnames
        kwargs = {name: funcargs[name] for name in argnames}
        asyncio.run(pyfuncitem.obj(**kwargs))
        outcome = yield
        outcome.force_result(True)
        return
    yield
