# SPDX-License-Identifier: Apache-2.0
"""Pure-Python JSON-Schema-2020-12 subset validator.

This module is the dependency-free fallback for ``jsonschema.validate``.
It is intentionally a *subset* validator: it implements exactly the
keywords used by the Wakir Phase-1b document schemas
(``aip-document/0.1.0``, ``federation-trust-document/0.1.0``).

The subset is documented and validated by an inventory grep at
test-time so the validator never silently passes a schema that uses
a keyword it does not understand. Unsupported keywords raise
:class:`NotImplementedError` loudly, signalling either "install
``jsonschema`` for full coverage" or "extend the subset".

References (URL-200-stamped 2026-05-07):

- JSON Schema 2020-12: <https://json-schema.org/draft/2020-12/schema>
- ECMA-262 RegExp (used by ``pattern``):
  <https://www.ecma-international.org/ecma-262/12.0/index.html#sec-regexp-regular-expression-objects>

Subset coverage
---------------

Implemented keywords:
- ``type``                  (string, integer, number, object, array, boolean, null)
- ``required``              (List[str])
- ``properties``            (Dict[str, Schema])
- ``additionalProperties``  (bool or Schema)
- ``enum``                  (List[Hashable])
- ``const``                 (any JSON-comparable value)
- ``pattern``               (str, ECMA-262-style regex; we use Python re)
- ``minLength``             (int)
- ``minItems``              (int)
- ``items``                 (Schema, applied to each array element)
- ``anyOf``                 (List[Schema], at least one must match)
- ``format`` for ``"uri"``, ``"date-time"`` (structural check, not RFC-3339-strict)

Refused keywords (raise NotImplementedError):
- ``$ref``, ``$defs``, ``oneOf``, ``allOf``, ``not``, ``if``/``then``/``else``,
  ``contains``, ``propertyNames``, ``patternProperties``,
  ``contentEncoding``, ``dependencies``, ``dependentRequired``,
  ``maxItems``, ``maxLength``, ``minimum``, ``maximum``, ``multipleOf``,
  ``uniqueItems``

The refused-list is **not** "we don't accept these forever"; it is "if
your schema uses one of these, fall back to ``jsonschema`` or extend
the subset". The Wakir Phase-1b schemas were audited and use only
the implemented set (see ``_SUPPORTED_KEYWORDS`` below).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse


__all__ = ["validate", "ValidationError"]


_SUPPORTED_KEYWORDS = frozenset(
    [
        # Validation keywords we implement.
        "type",
        "required",
        "properties",
        "additionalProperties",
        "enum",
        "const",
        "pattern",
        "minLength",
        "minItems",
        "items",
        "anyOf",
        "format",
        # Annotation-only keywords; ignored at validation time.
        "title",
        "description",
        "$schema",
        "$id",
        "$comment",
        "default",
        "examples",
        "deprecated",
        "readOnly",
        "writeOnly",
    ]
)

_SUPPORTED_FORMATS = frozenset(["uri", "date-time"])

_DATE_TIME_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(\.[0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$"
)


class ValidationError(ValueError):
    """Raised when ``instance`` violates ``schema``.

    Mirrors ``jsonschema.ValidationError`` for the message-handling
    surface but does not duplicate its full path-tracking; the message
    string includes the failing key when available.
    """


def validate(instance: object, schema: dict) -> None:
    """Validate ``instance`` against ``schema``.

    Args:
        instance: The value to validate.
        schema: A JSON-Schema-2020-12-subset schema dict.

    Raises:
        ValidationError: if ``instance`` violates ``schema``.
        NotImplementedError: if ``schema`` uses a keyword outside the
            documented subset.

    The validator is **structural-only**: it does not download
    ``$ref``-pointed schemas, evaluate ``$defs``, or apply
    ``patternProperties``. If your schema uses any of those, install
    ``jsonschema`` and route through it; the resolver indirection
    (``aip_signing._schema_validate``) does this automatically when
    ``jsonschema`` is importable.
    """
    _walk(instance, schema, path="$")


def _walk(instance: object, schema: dict, *, path: str) -> None:
    # Reject unsupported keywords loudly. This catches schema-evolution
    # mistakes early (a new keyword silently passes is the worst failure
    # mode for a security-sensitive validator).
    for key in schema:
        if key not in _SUPPORTED_KEYWORDS:
            raise NotImplementedError(
                f"Pure-Python schema validator does not support keyword "
                f"{key!r} at {path}; install `jsonschema` for full coverage "
                "or extend `_schema_pure._SUPPORTED_KEYWORDS`"
            )

    # 1. type
    if "type" in schema:
        _check_type(instance, schema["type"], path)

    # 2. enum / const
    if "enum" in schema:
        if instance not in schema["enum"]:
            raise ValidationError(
                f"{path}: value {instance!r} not in enum {schema['enum']!r}"
            )
    if "const" in schema:
        if instance != schema["const"]:
            raise ValidationError(
                f"{path}: value {instance!r} != const {schema['const']!r}"
            )

    # 3. anyOf — at least one branch must validate.
    if "anyOf" in schema:
        branches = schema["anyOf"]
        if not isinstance(branches, list) or not branches:
            raise ValidationError(f"{path}: anyOf must be a non-empty list of schemas")
        last_err: Exception | None = None
        matched = False
        for idx, sub in enumerate(branches):
            try:
                _walk(instance, sub, path=f"{path}#anyOf[{idx}]")
                matched = True
                break
            except ValidationError as exc:
                last_err = exc
        if not matched:
            raise ValidationError(
                f"{path}: value {instance!r} matched no anyOf branch "
                f"(last error: {last_err})"
            )

    # 4. string-typed checks
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            raise ValidationError(
                f"{path}: string length {len(instance)} < minLength {schema['minLength']}"
            )
        if "pattern" in schema:
            if not re.search(schema["pattern"], instance):
                raise ValidationError(
                    f"{path}: value {instance!r} does not match pattern "
                    f"{schema['pattern']!r}"
                )
        if "format" in schema:
            _check_format(instance, schema["format"], path)

    # 5. object-typed checks
    if isinstance(instance, dict):
        if "required" in schema:
            for key in schema["required"]:
                if key not in instance:
                    raise ValidationError(
                        f"{path}: required field {key!r} is missing"
                    )
        if "properties" in schema:
            for key, sub_schema in schema["properties"].items():
                if key in instance:
                    _walk(instance[key], sub_schema, path=f"{path}.{key}")
        if "additionalProperties" in schema:
            allowed = set(schema.get("properties", {}).keys())
            ap = schema["additionalProperties"]
            for key in instance.keys():
                if key in allowed:
                    continue
                if ap is False:
                    raise ValidationError(
                        f"{path}: additional property {key!r} is not allowed"
                    )
                if isinstance(ap, dict):
                    _walk(instance[key], ap, path=f"{path}.{key}")

    # 6. array-typed checks
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            raise ValidationError(
                f"{path}: array length {len(instance)} < minItems {schema['minItems']}"
            )
        if "items" in schema:
            for idx, item in enumerate(instance):
                _walk(item, schema["items"], path=f"{path}[{idx}]")


def _check_type(instance: object, type_spec: Any, path: str) -> None:
    # type can be a single string or a list of strings (per JSON Schema).
    if isinstance(type_spec, list):
        if not any(_matches_type(instance, t) for t in type_spec):
            raise ValidationError(
                f"{path}: value {instance!r} does not match any of "
                f"types {type_spec!r}"
            )
        return
    if not _matches_type(instance, type_spec):
        raise ValidationError(
            f"{path}: value {instance!r} (type "
            f"{type(instance).__name__}) is not of type {type_spec!r}"
        )


def _matches_type(instance: object, type_name: str) -> bool:
    if type_name == "string":
        return isinstance(instance, str)
    if type_name == "integer":
        return isinstance(instance, int) and not isinstance(instance, bool)
    if type_name == "number":
        return (
            isinstance(instance, (int, float)) and not isinstance(instance, bool)
        )
    if type_name == "boolean":
        return isinstance(instance, bool)
    if type_name == "object":
        return isinstance(instance, dict)
    if type_name == "array":
        return isinstance(instance, list)
    if type_name == "null":
        return instance is None
    raise NotImplementedError(
        f"Pure-Python schema validator does not support type {type_name!r}; "
        "install `jsonschema` for full coverage"
    )


def _check_format(instance: str, format_name: str, path: str) -> None:
    if format_name not in _SUPPORTED_FORMATS:
        # Per JSON-Schema spec, format is annotation-only by default.
        # We mimic jsonschema's default behaviour: unknown formats pass
        # silently. This keeps us strict-compatible.
        return
    if format_name == "uri":
        try:
            parsed = urlparse(instance)
        except (ValueError, AttributeError):
            raise ValidationError(
                f"{path}: value {instance!r} is not a parseable URI"
            )
        if not parsed.scheme:
            raise ValidationError(
                f"{path}: URI {instance!r} has no scheme"
            )
    elif format_name == "date-time":
        if not _DATE_TIME_RE.match(instance):
            raise ValidationError(
                f"{path}: value {instance!r} is not a valid RFC 3339 date-time"
            )
