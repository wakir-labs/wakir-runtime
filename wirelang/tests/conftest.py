# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for Wirelang Layer 0-2 schema-compliance tests.

Loads the three Layer-0/1/2 JSON-Schema documents and the example frames,
and exposes them as pytest fixtures consumed by the per-layer test modules.

Sandbox-CI note (Tag-11)
------------------------

The validator fixtures lazy-import :mod:`jsonschema` via
:func:`pytest.importorskip`. When ``jsonschema`` is not installed (the
sandbox-CI baseline), the validator-consuming tests are skipped, while
the schema-loading and pure-Python-fallback tests still run. This keeps
the suite green in a `rfc8785`/`jsonschema`-free sandbox while preserving
full coverage in the production-CI environment where both libraries are
present.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Asyncio test support (Sprint-Pengine-10 OI-PEFR-6/7 hermetic tests).
#
# We do NOT depend on pytest-asyncio (Bug-34c structural-fix discipline:
# the test surface stays pure-stdlib + pytest). Instead we register a
# minimal collection hook that runs ``@pytest.mark.asyncio``-decorated
# test functions through ``asyncio.run``.
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "asyncio: run the test coroutine with asyncio.run (Sprint-Pengine-10).",
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
        # Suppress the default pyfunc call (already run above).
        outcome.force_result(True)
        return
    yield

WIRELANG_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = WIRELANG_ROOT / "schemas"
EXAMPLE_DIR = WIRELANG_ROOT / "examples"


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture(scope="session")
def layer_0_schema() -> dict:
    return _load_json(SCHEMA_DIR / "layer-0-transport.json")


@pytest.fixture(scope="session")
def layer_1_schema() -> dict:
    return _load_json(SCHEMA_DIR / "layer-1-wire.json")


@pytest.fixture(scope="session")
def layer_2_schema() -> dict:
    return _load_json(SCHEMA_DIR / "layer-2-semantic.json")


@pytest.fixture(scope="session")
def layer_0_validator(layer_0_schema: dict):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(layer_0_schema)
    return jsonschema.Draft202012Validator(layer_0_schema)


@pytest.fixture(scope="session")
def layer_1_validator(layer_1_schema: dict):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(layer_1_schema)
    return jsonschema.Draft202012Validator(layer_1_schema)


@pytest.fixture(scope="session")
def layer_2_validator(layer_2_schema: dict):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(layer_2_schema)
    return jsonschema.Draft202012Validator(layer_2_schema)


@pytest.fixture(scope="session")
def layer_3_capability_token_schema() -> dict:
    return _load_json(SCHEMA_DIR / "layer-3-capability-token.json")


@pytest.fixture(scope="session")
def aip_document_schema() -> dict:
    return _load_json(SCHEMA_DIR / "aip-document.json")


@pytest.fixture(scope="session")
def layer_3_capability_token_validator(
    layer_3_capability_token_schema: dict,
):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(layer_3_capability_token_schema)
    return jsonschema.Draft202012Validator(layer_3_capability_token_schema)


@pytest.fixture(scope="session")
def aip_document_validator(aip_document_schema: dict):
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.Draft202012Validator.check_schema(aip_document_schema)
    return jsonschema.Draft202012Validator(aip_document_schema)


@pytest.fixture(scope="session")
def example_domain_event() -> dict:
    return _load_json(EXAMPLE_DIR / "frame-domain-event-example.json")


@pytest.fixture(scope="session")
def example_meta_event() -> dict:
    return _load_json(EXAMPLE_DIR / "frame-meta-event-example.json")


@pytest.fixture(scope="session")
def example_capability_token() -> dict:
    return _load_json(EXAMPLE_DIR / "capability-token-example.json")


@pytest.fixture(scope="session")
def example_aip_document() -> dict:
    return _load_json(EXAMPLE_DIR / "aip-document-example.json")
