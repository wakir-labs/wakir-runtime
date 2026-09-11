# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Hermetic tests for ``tooling/compat/compat_canonical.py``.

No network, no repo checkout: schemas are built inline.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("rfc8785")

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLING = REPO_ROOT / "tooling" / "compat"


def _load(name: str):
    if str(TOOLING) not in sys.path:
        sys.path.insert(0, str(TOOLING))
    spec = importlib.util.spec_from_file_location(name, TOOLING / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


canon = _load("compat_canonical")


BASE = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://example.invalid/schema/thing/1.0.0",
    "title": "thing",
    "description": "top-level prose",
    "x-spdx-license-identifier": "LICENSE-A",
    "x-spdx-file-copyright-text": "someone",
    "type": "object",
    "required": ["kind"],
    "properties": {
        "kind": {
            "type": "string",
            "enum": ["a", "b"],
            "description": "nested prose",
        },
        "items": {
            "type": "array",
            "items": {"type": "object", "description": "deep prose", "properties": {"x": {"type": "integer"}}},
        },
    },
    "$defs": {"h": {"type": "string", "pattern": "^[0-9a-f]{64}$", "description": "hex"}},
}


def _variant(**changes):
    doc = json.loads(json.dumps(BASE))
    for path, value in changes.items():
        node = doc
        parts = path.split(".")
        for part in parts[:-1]:
            node = node[part]
        if value is None:
            node.pop(parts[-1], None)
        else:
            node[parts[-1]] = value
    return doc


def test_strip_removes_x_spdx_and_description_at_every_level():
    stripped = canon.strip_non_canonical(BASE)
    assert "description" not in stripped
    assert not any(k.startswith("x-spdx-") for k in stripped)
    assert "description" not in stripped["properties"]["kind"]
    assert "description" not in stripped["properties"]["items"]["items"]
    assert "description" not in stripped["$defs"]["h"]
    # Contract keys survive.
    assert stripped["properties"]["kind"]["enum"] == ["a", "b"]
    assert stripped["$defs"]["h"]["pattern"] == "^[0-9a-f]{64}$"
    assert stripped["$id"] == BASE["$id"]
    assert stripped["title"] == BASE["title"]


def test_strip_keeps_non_string_description_and_x_spdx_members():
    """Persona schemas *define* a property named ``description``; only
    string-valued prose is stripped, the property definition is contract."""
    doc = {
        "description": "prose",
        "x-spdx-license-identifier": "LICENSE-A",
        "x-spdx-extra": {"nested": "object"},
        "properties": {
            "description": {"type": "string", "maxLength": 200, "description": "prose about the field"},
        },
    }
    stripped = canon.strip_non_canonical(doc)
    assert "description" not in stripped
    assert "x-spdx-license-identifier" not in stripped
    assert stripped["x-spdx-extra"] == {"nested": "object"}
    assert stripped["properties"]["description"] == {"type": "string", "maxLength": 200}
    # Changing the *property definition* changes the digest.
    doc2 = json.loads(json.dumps(doc))
    doc2["properties"]["description"]["maxLength"] = 100
    assert canon.canonical_digest(doc) != canon.canonical_digest(doc2)


def test_is_stripped_member_semantics():
    assert canon.is_stripped_member("description", "text")
    assert canon.is_stripped_member("x-spdx-license-identifier", "X")
    assert not canon.is_stripped_member("description", {"type": "string"})
    assert not canon.is_stripped_member("x-spdx-foo", ["list"])
    assert not canon.is_stripped_member("title", "text")
    assert not canon.is_stripped_member("x-canonical-home", "wakir-protocol")


def test_strip_does_not_mutate_input():
    before = json.dumps(BASE, sort_keys=True)
    canon.strip_non_canonical(BASE)
    assert json.dumps(BASE, sort_keys=True) == before


def test_digest_ignores_formatting_licence_header_and_prose(tmp_path: Path):
    compact = tmp_path / "compact.json"
    pretty = tmp_path / "pretty.json"
    compact.write_text(json.dumps(BASE, separators=(",", ":")), encoding="utf-8")
    other = _variant(
        **{
            "description": "changed prose",
            "x-spdx-license-identifier": "LICENSE-B",
            "properties.kind.description": None,
            "properties.items.items.description": "other deep prose",
        }
    )
    pretty.write_text(json.dumps(other, indent=4, sort_keys=False), encoding="utf-8")
    assert canon.canonical_digest_of_file(compact) == canon.canonical_digest_of_file(pretty)


@pytest.mark.parametrize(
    "path,value",
    [
        ("properties.kind.enum", ["a", "b", "c"]),
        ("properties.kind.enum", ["a"]),
        ("required", ["kind", "items"]),
        ("$defs.h.pattern", "^[0-9a-f]{40}$"),
        ("$id", "https://example.invalid/schema/thing/2.0.0"),
        ("title", "renamed"),
        ("properties.items.items.properties.x.type", "string"),
    ],
)
def test_digest_changes_on_contract_change(path, value):
    assert canon.canonical_digest(BASE) != canon.canonical_digest(_variant(**{path: value}))


def test_digest_is_jcs_key_order_independent():
    reordered = {k: BASE[k] for k in reversed(list(BASE))}
    assert canon.canonical_digest(BASE) == canon.canonical_digest(reordered)


def test_stub_detection():
    assert canon.is_stub_schema({"x-status": "stub"})
    assert not canon.is_stub_schema({"x-status": "canonical"})
    assert not canon.is_stub_schema(BASE)
    assert not canon.is_stub_schema(["not", "a", "dict"])


def test_cli_prints_sha256sum_style(tmp_path: Path, capsys):
    target = tmp_path / "s.json"
    target.write_text(json.dumps(BASE), encoding="utf-8")
    assert canon.main([str(target)]) == 0
    out = capsys.readouterr().out.strip()
    digest, _, printed_path = out.partition("  ")
    assert len(digest) == 64
    assert printed_path == str(target)
    assert digest == canon.canonical_digest(BASE)
