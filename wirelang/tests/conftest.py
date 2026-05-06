# SPDX-License-Identifier: Apache-2.0
"""Shared pytest fixtures for Wirelang Layer 0-2 schema-compliance tests.

Loads the three Layer-0/1/2 JSON-Schema documents and the example frames,
and exposes them as pytest fixtures consumed by the per-layer test modules.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

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
def layer_0_validator(layer_0_schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(layer_0_schema)
    return Draft202012Validator(layer_0_schema)


@pytest.fixture(scope="session")
def layer_1_validator(layer_1_schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(layer_1_schema)
    return Draft202012Validator(layer_1_schema)


@pytest.fixture(scope="session")
def layer_2_validator(layer_2_schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(layer_2_schema)
    return Draft202012Validator(layer_2_schema)


@pytest.fixture(scope="session")
def layer_3_capability_token_schema() -> dict:
    return _load_json(SCHEMA_DIR / "layer-3-capability-token.json")


@pytest.fixture(scope="session")
def aip_document_schema() -> dict:
    return _load_json(SCHEMA_DIR / "aip-document.json")


@pytest.fixture(scope="session")
def layer_3_capability_token_validator(
    layer_3_capability_token_schema: dict,
) -> Draft202012Validator:
    Draft202012Validator.check_schema(layer_3_capability_token_schema)
    return Draft202012Validator(layer_3_capability_token_schema)


@pytest.fixture(scope="session")
def aip_document_validator(aip_document_schema: dict) -> Draft202012Validator:
    Draft202012Validator.check_schema(aip_document_schema)
    return Draft202012Validator(aip_document_schema)


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
