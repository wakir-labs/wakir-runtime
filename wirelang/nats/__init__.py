# SPDX-License-Identifier: Apache-2.0
"""Wirelang NATS transport-binding helpers.

Phase-1b Sprint-2 Tag-1 introduces ``subject_mapping``: a deterministic
build/parse/validate utility for the Wakir NATS subject convention
defined in ``specs/nats-subject-mapping-v1.md``.

The package is import-light and depends on the standard library only.
"""

from __future__ import annotations

from .subject_mapping import (
    SubjectV1,
    SubjectFormatError,
    build_subject,
    parse_subject,
    roundtrip,
    validate_stream_pattern,
    validate_consumer_filter,
    schema_for_subject,
    persona_slug,
    tv_anchor,
    federation_host_slug,
    RESERVED_DOMAINS,
    RESERVED_EVENT_TYPES,
)

__all__ = [
    "SubjectV1",
    "SubjectFormatError",
    "build_subject",
    "parse_subject",
    "roundtrip",
    "validate_stream_pattern",
    "validate_consumer_filter",
    "schema_for_subject",
    "persona_slug",
    "tv_anchor",
    "federation_host_slug",
    "RESERVED_DOMAINS",
    "RESERVED_EVENT_TYPES",
]
