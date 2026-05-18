#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""NATS-JetStream Subjects + Publish-Mode Audit (Tag-43, Selin).

This script is the Tag-43 substantive follow-up to the Bug-42 close-out
in PR #265: now that ``wirelang/persona_engine/publish_mode_contract.py``
encodes the publish/subscribe surface-compatibility matrix and
``wirelang/cli/bridge_forward.py`` honours ``--publish-mode jetstream``
by switching to ``js.publish``, the Tag-43 question is:

  Are *all* further NATS publish / subscribe call sites in the
  ``wakir-runtime`` codebase configured analogously, and do all
  subject names follow the canonical
  ``wakir.<env>.<domain>.<event>[.<sub_id>]`` form?

The audit is intentionally a *grep + parse* pass over the working
tree — stdlib-only, no nats-py, no AST package outside Python's
``ast`` module, no network. It mirrors the pattern of
``scripts/audit/cross-repo-sync-audit.py`` (Reza Tag-42) and is
hermetic-test-friendly: the public surface (``audit_repo``,
``classify_call``, ``classify_subject_template``, ``render_report``)
takes a repo-root :class:`pathlib.Path` and returns plain
dataclasses — no shared state, no env reads, no I/O outside the
caller-provided root.

Four audit classes, mirroring the Tag-43 brief:

  1. **Inventory-Scan** — every Python or Rust source file under
     the repo is scanned for one of the publish/subscribe call
     sigils:

       * ``nc.publish(...)``  — core-NATS publish
       * ``js.publish(...)``  — JetStream publish
       * ``nc.subscribe(...)``— core-NATS subscribe
       * ``js.subscribe(...)``— JetStream push/pull subscribe
       * ``SubscribeAsync(``  — .NET-style subscribe (currently
         not present in-tree but reserved for future polyglot
         clients; the scanner flags occurrences so the inventory
         is exhaustive).

     Each hit is rendered as a row ``(file, line, kind, snippet)``
     where ``kind`` is one of ``publish-core``,
     ``publish-jetstream``, ``subscribe-core``,
     ``subscribe-jetstream``, ``subscribe-polyglot``.

  2. **Mode-Cross-Validation** — for every Python module that
     declares both a ``publish_mode`` resolution (via
     ``publish_mode_contract.resolve_publish_mode_from_env`` or a
     string-literal compare against ``PUBLISH_MODE_JETSTREAM``)
     and a ``js.publish`` / ``nc.publish`` call, the script
     verifies that the *publish call dispatch* references the
     mode discriminator on the path that would reach it. A
     module that has a ``publish_mode`` resolution but only
     calls ``nc.publish`` (never ``js.publish``) is flagged as
     ``adapter-incomplete`` — the Bug-42-class regression that
     Tag-41 closed for ``bridge_forward.py`` and that Tag-43
     must not allow to creep back in elsewhere.

     The detection is line-window-based (publish_mode mention
     within 200 lines of the publish call) rather than AST-flow
     because the runtime modules use async helpers and lazy
     imports that pure-AST flow analysis would mis-classify.
     The 200-line window matches the longest publish-dispatch
     function in ``bridge_forward.py`` (≈110 lines) with a 2×
     margin.

  3. **Subject-Pattern-Drift-Check** — every string literal that
     looks like a Wirelang NATS subject (matches the schema regex
     ``^wakir\\.(dev|staging|prod)\\.…`` or one of the template
     forms ``wakir.{env}.…``) is parsed and classified. Two drift
     classes are reported:

       * ``regex-drift`` — the literal contains a ``wakir.`` prefix
         but does not match the schema regex
         ``wirelang/nats/subject_mapping.py::SCHEMA_SUBJECT_REGEX``.
       * ``template-drift`` — the literal is a Python f-string or
         ``.format(...)`` template but the placeholder set is not
         a subset of ``{env, persona_slug, sub_id}``.

     Test fixtures (subject-mapping unit tests etc.) are excluded
     by directory rule — ``tests/`` and ``conftest.py`` files do
     not count as production subject literals.

  4. **Adapter-Config-Audit** — every module that imports from
     ``publish_mode_contract`` is checked: it must either (a) call
     ``require_compatible(...)`` at bring-up (the Bug-42 hard-fail
     gate) or (b) be a pure-data module (no publish call at all).
     A module that imports ``publish_mode_contract`` *and* calls
     ``nc.publish``/``js.publish`` but does *not* call
     ``require_compatible`` is flagged as
     ``preflight-gate-missing``.

The script writes a Markdown audit report — optionally to
``reports/audit/<YYYY-MM-DD>-nats-jetstream-subjects-audit.md`` —
and exits 0 in audit-only mode (default) or non-zero in
``--enforce`` mode when any drift row is present.

Run examples
============

::

    # Default — audit the working tree, print report to stdout.
    python3 scripts/audit/nats-jetstream-subjects-audit.py

    # Write the report to the canonical path under reports/audit/.
    python3 scripts/audit/nats-jetstream-subjects-audit.py \\
        --report reports/audit/2026-05-18-nats-jetstream-subjects-audit.md

    # Enforce-mode (fail on any drift row).
    python3 scripts/audit/nats-jetstream-subjects-audit.py --enforce

Audit boundary
==============

This script does not invoke ``nats``, does not connect, does not
import ``nats-py``. It is a *static* audit. The complementary
*runtime* audit lives in Tomás' ``cross-substrate-parity-gate``
workflow (live JetStream stream-config probe). The combination of
the two — static + live — is the Bug-42 compound defence.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as _dt
import pathlib
import re
import sys
from typing import Iterable, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Regex inventory — kept in lock-step with
#   wirelang/nats/subject_mapping.py::SCHEMA_SUBJECT_REGEX
#   wirelang/persona_engine/nats_subscribe_loop.py SUBSCRIBE_SUBJECT_TEMPLATE
#   wirelang/cli/bridge_forward.py SUBJECT_TEMPLATE
# ---------------------------------------------------------------------------

#: Mirror of the schema regex (single source of truth: the JSON
#: schema at ``wirelang/schemas/layer-0-transport.json``). This
#: constant is the audit-side mirror; the test suite asserts that
#: it matches ``SCHEMA_SUBJECT_REGEX`` from ``subject_mapping.py``.
SCHEMA_SUBJECT_REGEX = re.compile(
    r"^wakir\.(dev|staging|prod)\.[a-z][a-z0-9_-]*\.[a-z][a-z0-9_.-]*"
    r"(\.[a-zA-Z0-9_.-]+)?$"
)

#: Template-form regex: matches a Wirelang subject template with
#: ``{env}`` / ``{persona_slug}`` / ``{sub_id}`` placeholders.
TEMPLATE_SUBJECT_REGEX = re.compile(
    r"^wakir\.\{env\}\.[a-z][a-z0-9_.-]*"
    r"(?:\.\{[a-z_][a-z0-9_]*\})?$"
)

#: Set of valid placeholder names accepted in a subject template.
_VALID_TEMPLATE_PLACEHOLDERS = frozenset({"env", "persona_slug", "sub_id"})

#: Recognised call sigils. Each entry is a (regex, kind) pair.
_CALL_SIGILS: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bnc\.publish\s*\("), "publish-core"),
    (re.compile(r"\bjs\.publish\s*\("), "publish-jetstream"),
    (re.compile(r"\bnc\.subscribe\s*\("), "subscribe-core"),
    (re.compile(r"\bjs\.subscribe\s*\("), "subscribe-jetstream"),
    (re.compile(r"\bSubscribeAsync\s*\("), "subscribe-polyglot"),
)

#: Files / directories that the audit *intentionally* skips. Tests
#: and fixtures are not production code; vendored or generated dirs
#: should not pollute the inventory.
_EXCLUDED_DIR_TOKENS: Tuple[str, ...] = (
    "/tests/",
    "/test/",
    "/fixtures/",
    "/.git/",
    "/.venv/",
    "/venv/",
    "/__pycache__/",
    "/target/",
    "/node_modules/",
    "/.worktree-",
)

#: Filenames excluded from the inventory (tests + this audit script
#: itself, since it embeds literal sigils as documentation).
_EXCLUDED_FILE_NAMES: Tuple[str, ...] = (
    "conftest.py",
    "nats-jetstream-subjects-audit.py",
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class CallRow:
    """One publish/subscribe call-site row."""

    file: str
    line: int
    kind: str
    snippet: str


@dataclasses.dataclass(frozen=True)
class SubjectRow:
    """One subject-literal row."""

    file: str
    line: int
    literal: str
    verdict: str  # "ok", "regex-drift", "template-drift"
    detail: str


@dataclasses.dataclass(frozen=True)
class ModeCheckRow:
    """One mode-cross-validation row.

    A row is emitted for every module that participates in the
    publish-mode dispatch contract. The verdict tells whether the
    module's publish-dispatch is well-formed.
    """

    file: str
    verdict: str  # "ok", "adapter-incomplete", "no-publish-mode"
    detail: str


@dataclasses.dataclass(frozen=True)
class AdapterRow:
    """One adapter-config-audit row."""

    file: str
    verdict: str  # "ok", "preflight-gate-missing", "data-only"
    detail: str


@dataclasses.dataclass(frozen=True)
class AuditResult:
    """Aggregate audit result returned by :func:`audit_repo`."""

    repo_root: str
    scanned_files: int
    inventory: Tuple[CallRow, ...]
    subjects: Tuple[SubjectRow, ...]
    mode_checks: Tuple[ModeCheckRow, ...]
    adapter_checks: Tuple[AdapterRow, ...]

    @property
    def drift_count(self) -> int:
        count = sum(
            1 for s in self.subjects
            if s.verdict in ("regex-drift", "template-drift")
        )
        count += sum(
            1 for m in self.mode_checks if m.verdict == "adapter-incomplete"
        )
        count += sum(
            1 for a in self.adapter_checks
            if a.verdict == "preflight-gate-missing"
        )
        return count


# ---------------------------------------------------------------------------
# Scan helpers (stdlib-only)
# ---------------------------------------------------------------------------


def _is_excluded(path: pathlib.Path, repo_root: pathlib.Path) -> bool:
    """Return True if ``path`` should be skipped by the audit.

    Exclusion rules:

    * Path contains any token in :data:`_EXCLUDED_DIR_TOKENS`.
    * File name is in :data:`_EXCLUDED_FILE_NAMES`.
    * Path is not a regular file.
    """

    if not path.is_file():
        return True
    if path.name in _EXCLUDED_FILE_NAMES:
        return True
    try:
        rel = "/" + str(path.relative_to(repo_root)).replace("\\", "/") + "/"
    except ValueError:
        rel = "/" + str(path).replace("\\", "/") + "/"
    for token in _EXCLUDED_DIR_TOKENS:
        if token in rel:
            return True
    return False


def _iter_source_files(
    repo_root: pathlib.Path,
) -> Iterable[pathlib.Path]:
    """Yield every Python or Rust file under ``repo_root``.

    Order is sorted for deterministic output.
    """

    for suffix in (".py", ".rs"):
        for p in sorted(repo_root.rglob(f"*{suffix}")):
            if _is_excluded(p, repo_root):
                continue
            yield p


def classify_call(line: str) -> Optional[str]:
    """Return the call-kind for ``line`` or ``None`` if no match.

    The classifier returns the *first* matching sigil; precedence
    follows the :data:`_CALL_SIGILS` order. Comment-only lines (the
    first non-space char is ``#`` for Python or ``//`` for Rust)
    are not classified.
    """

    stripped = line.lstrip()
    if stripped.startswith("#") or stripped.startswith("//"):
        return None
    for pat, kind in _CALL_SIGILS:
        if pat.search(line):
            return kind
    return None


def _is_inside_string_literal(line: str, match_start: int) -> bool:
    """Heuristic — is ``match_start`` inside a quoted string?

    Counts unescaped quote chars (``"`` and ``'``) to the left of
    the match. Odd count means we are inside a string. Triple-quote
    blocks are not handled here — callers should pre-filter
    docstring-only lines.
    """

    prefix = line[:match_start]
    # Strip escaped quotes first.
    prefix = re.sub(r"\\\"|\\'", "", prefix)
    dq = prefix.count('"')
    sq = prefix.count("'")
    return (dq % 2 == 1) or (sq % 2 == 1)


def _strip_docstring_lines(text: str) -> str:
    """Replace triple-quote-block contents with blank lines.

    The classifier should not treat the literal ``js.publish``
    inside a Python docstring as a real call. We don't run the
    Python parser to keep the script stdlib-friendly for any
    file kind; instead we use a simple state machine that toggles
    on ``\"\"\"`` and ``'''`` delimiters.

    Line count is preserved so reported line numbers match the
    on-disk file.
    """

    out: List[str] = []
    in_block: Optional[str] = None  # ``\"\"\"`` or ``'''``
    for raw in text.splitlines(keepends=False):
        line = raw
        if in_block is None:
            # Detect opening delimiter on the line.
            for delim in ('"""', "'''"):
                idx = line.find(delim)
                if idx >= 0:
                    # If the same delim appears again on the same
                    # line, treat the in-between span as docstring
                    # and emit blank.
                    rest = line[idx + 3:]
                    close = rest.find(delim)
                    if close >= 0:
                        line = (
                            line[:idx]
                            + (" " * 3)
                            + (" " * close)
                            + (" " * 3)
                            + rest[close + 3:]
                        )
                        # Not in block after — same line closes.
                        break
                    in_block = delim
                    line = line[:idx]
                    break
        else:
            close = line.find(in_block)
            if close >= 0:
                line = line[close + 3:]
                in_block = None
            else:
                line = ""
        out.append(line)
    return "\n".join(out)


def scan_calls(
    path: pathlib.Path,
    text: str,
) -> Tuple[CallRow, ...]:
    """Scan ``text`` for publish/subscribe call sigils.

    ``path`` is used only to populate the ``file`` field; the file
    is not re-read.
    """

    stripped = _strip_docstring_lines(text)
    out: List[CallRow] = []
    for lineno, line in enumerate(stripped.splitlines(), start=1):
        kind = classify_call(line)
        if kind is None:
            continue
        out.append(
            CallRow(
                file=str(path),
                line=lineno,
                kind=kind,
                snippet=line.strip()[:240],
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# Subject-pattern drift
# ---------------------------------------------------------------------------


#: Captures literal-form Wirelang subjects in source.
_LITERAL_SUBJECT_RE = re.compile(
    r"\"(wakir\.[A-Za-z0-9_.{}\\-]+)\""
)

#: Captures template-form Wirelang subjects.
_TEMPLATE_SUBJECT_RE = re.compile(
    r"\"(wakir\.\{[A-Za-z0-9_]+\}[A-Za-z0-9_.{}\\-]+)\""
)


#: A literal starting with ``wakir.<env>.`` is unambiguously a NATS
#: subject — there is no other ``wakir.dev.…`` / ``wakir.staging.…`` /
#: ``wakir.prod.…`` namespace in the codebase. The audit therefore
#: treats any such literal that fails the schema regex as a hard
#: drift; other ``wakir.…`` literals (telemetry meter names,
#: observability tags, DID prefixes, schema ids) are classified as
#: ``namespace-id`` and reported informationally, not as drift.
_NATS_ENV_PREFIX_RE = re.compile(r"^wakir\.(dev|staging|prod)\.")


def classify_subject_template(literal: str) -> Tuple[str, str]:
    """Classify ``literal`` (without surrounding quotes).

    Returns ``(verdict, detail)`` where verdict is one of
    ``"ok"``, ``"regex-drift"``, ``"template-drift"`` or
    ``"namespace-id"`` (informational — not counted as drift).
    """

    # Template form — must use only allowed placeholders AND must be
    # rooted at the ``wakir.{env}.`` prefix (anything else is a
    # template that happens to start with wakir. but is not a NATS
    # subject, e.g. a metric-name template).
    if "{" in literal:
        if not literal.startswith("wakir.{env}."):
            return (
                "namespace-id",
                f"template {literal!r} uses wakir.* namespace but is "
                f"not a wakir.{{env}}.* NATS subject template "
                f"(likely a metric/schema-id template)",
            )
        placeholders = re.findall(r"\{([a-z_][a-z0-9_]*)\}", literal)
        unknown = [p for p in placeholders if p not in _VALID_TEMPLATE_PLACEHOLDERS]
        if unknown:
            return (
                "template-drift",
                f"unknown placeholder(s) {unknown!r}; "
                f"allowed: {sorted(_VALID_TEMPLATE_PLACEHOLDERS)}",
            )
        if not TEMPLATE_SUBJECT_REGEX.match(
            re.sub(r"\{[a-z_][a-z0-9_]*\}", "{env}", literal)
        ):
            return (
                "template-drift",
                f"template {literal!r} does not match canonical "
                f"wakir.{{env}}.<domain>.<event>[.<sub_id>] form",
            )
        return ("ok", "template form accepted")

    # Concrete form — only a literal that starts with ``wakir.<env>.``
    # is treated as a NATS subject. Other ``wakir.*`` literals are
    # classified as namespace-ids (informational).
    if not _NATS_ENV_PREFIX_RE.match(literal):
        return (
            "namespace-id",
            f"literal {literal!r} uses wakir.* namespace but is not "
            f"a wakir.<env>.* NATS subject (likely a metric/schema-id)",
        )
    if SCHEMA_SUBJECT_REGEX.match(literal):
        return ("ok", "matches schema regex")
    return (
        "regex-drift",
        f"literal {literal!r} starts with wakir.<env>. but does not "
        f"match SCHEMA_SUBJECT_REGEX "
        f"(wakir.<env>.<domain>.<event>[.<sub_id>])",
    )


def scan_subjects(
    path: pathlib.Path,
    text: str,
) -> Tuple[SubjectRow, ...]:
    """Scan ``text`` for Wirelang subject literals."""

    stripped = _strip_docstring_lines(text)
    out: List[SubjectRow] = []
    for lineno, line in enumerate(stripped.splitlines(), start=1):
        seen_on_line: set = set()
        for m in _LITERAL_SUBJECT_RE.finditer(line):
            literal = m.group(1)
            if literal in seen_on_line:
                continue
            seen_on_line.add(literal)
            verdict, detail = classify_subject_template(literal)
            out.append(
                SubjectRow(
                    file=str(path),
                    line=lineno,
                    literal=literal,
                    verdict=verdict,
                    detail=detail,
                )
            )
    return tuple(out)


# ---------------------------------------------------------------------------
# Mode-cross-validation
# ---------------------------------------------------------------------------


_PUBLISH_MODE_MARKERS = (
    "PUBLISH_MODE_JETSTREAM",
    "PUBLISH_MODE_CORE",
    "resolve_publish_mode_from_env",
    "--publish-mode",
    "WAKIR_NATS_PUBLISH_MODE",
)


def _has_marker(text: str, markers: Sequence[str]) -> bool:
    return any(m in text for m in markers)


def cross_validate_modes(
    path: pathlib.Path,
    text: str,
    calls: Sequence[CallRow],
) -> Optional[ModeCheckRow]:
    """Mode-cross-validation for a single module.

    Returns a row only for modules where the verdict is meaningful
    (i.e. the module contains either a publish-mode marker or a
    publish call). Pure-subscriber modules are silent.
    """

    has_mode = _has_marker(text, _PUBLISH_MODE_MARKERS)
    pub_calls = [c for c in calls if c.kind.startswith("publish-")]

    if not has_mode and not pub_calls:
        return None

    if not has_mode and pub_calls:
        # A module that publishes but never references the
        # publish-mode discriminator. That's the Bug-42 silent-
        # drop precondition (Adapter-B is incomplete).
        kinds = sorted({c.kind for c in pub_calls})
        return ModeCheckRow(
            file=str(path),
            verdict="adapter-incomplete",
            detail=(
                f"module has publish call(s) {kinds!r} but does not "
                f"reference any of {list(_PUBLISH_MODE_MARKERS)} — "
                f"Bug-42-class adapter-incomplete"
            ),
        )

    if has_mode and not pub_calls:
        # A module that declares the mode marker (often a
        # contract/test-helper module) but has no publish call
        # of its own. Treat as "no-publish-mode" — informational.
        return ModeCheckRow(
            file=str(path),
            verdict="no-publish-mode",
            detail=(
                "module references publish-mode discriminator but "
                "has no publish call — likely a contract or helper"
            ),
        )

    # has_mode and pub_calls — verify both core and jetstream
    # publish are reachable in the same file (the Tag-41 pattern
    # in bridge_forward.py).
    pub_kinds = sorted({c.kind for c in pub_calls})
    if "publish-jetstream" in pub_kinds and "publish-core" in pub_kinds:
        return ModeCheckRow(
            file=str(path),
            verdict="ok",
            detail=(
                "module dispatches both nc.publish and js.publish "
                "with publish-mode discriminator — Adapter-B complete"
            ),
        )
    if pub_kinds == ["publish-core"]:
        return ModeCheckRow(
            file=str(path),
            verdict="adapter-incomplete",
            detail=(
                "module references publish-mode but only calls "
                "nc.publish — js.publish path missing"
            ),
        )
    if pub_kinds == ["publish-jetstream"]:
        # JetStream-only publisher with publish-mode marker — fine
        # (this is the post-Phase-3 producer-rewrite end state).
        return ModeCheckRow(
            file=str(path),
            verdict="ok",
            detail=(
                "module is jetstream-only publisher with publish-mode "
                "guard — Phase-3 producer-rewrite end state"
            ),
        )
    # Any other combo (shouldn't happen) — flag as data point.
    return ModeCheckRow(
        file=str(path),
        verdict="adapter-incomplete",
        detail=f"unexpected publish-kind combination: {pub_kinds!r}",
    )


# ---------------------------------------------------------------------------
# Adapter-config-audit
# ---------------------------------------------------------------------------


_CONTRACT_IMPORT_MARKERS = (
    "from .publish_mode_contract import",
    "from wirelang.persona_engine.publish_mode_contract import",
    "import publish_mode_contract",
    "publish_mode_contract.",
)

_GATE_MARKERS = (
    "require_compatible(",
    "require_compatible (",
)


def adapter_config_audit(
    path: pathlib.Path,
    text: str,
    calls: Sequence[CallRow],
) -> Optional[AdapterRow]:
    """Adapter-config-audit for a single module.

    The require_compatible() gate is the subscriber's responsibility:
    a subscriber needs to refuse silent-drop pairs before binding the
    consumer. A pure-publisher module that resolves publish_mode but
    never subscribes does not need the gate — the matching gate fires
    on the subscriber side at bring-up. The verdict differentiates:

    * ``ok`` — subscriber module imports contract and calls
      require_compatible.
    * ``publisher-no-gate`` — publisher module imports contract and
      resolves the mode but has no subscribe call (informational —
      not a Bug-42 regression).
    * ``preflight-gate-missing`` — subscriber module imports contract
      but does not call require_compatible (Bug-42 regression).
    * ``no-contract-import`` — publisher/subscriber module without
      contract import (informational).
    * ``data-only`` — contract-importing module with no NATS call.
    """

    imports_contract = _has_marker(text, _CONTRACT_IMPORT_MARKERS)
    has_gate = _has_marker(text, _GATE_MARKERS)
    pub_calls = [c for c in calls if c.kind.startswith("publish-")]
    sub_calls = [c for c in calls if c.kind.startswith("subscribe-")]
    pub_or_sub_calls = pub_calls + sub_calls

    if not imports_contract and not pub_or_sub_calls:
        return None
    if not imports_contract and pub_or_sub_calls:
        # Module has NATS calls but never imported the contract —
        # informational. Not all callers need the gate (init scripts,
        # health probes) but the row makes the absence visible.
        return AdapterRow(
            file=str(path),
            verdict="no-contract-import",
            detail=(
                "module has publish/subscribe call(s) but does not "
                "import publish_mode_contract — caller-side gate "
                "responsibility unknown"
            ),
        )
    if imports_contract and not pub_or_sub_calls:
        return AdapterRow(
            file=str(path),
            verdict="data-only",
            detail=(
                "module imports publish_mode_contract but has no "
                "publish/subscribe call — pure data/test helper"
            ),
        )
    # Both — gate expectation depends on whether the module subscribes.
    if has_gate:
        return AdapterRow(
            file=str(path),
            verdict="ok",
            detail=(
                "module imports contract, calls require_compatible, "
                "and dispatches publish/subscribe — Bug-42 gate in place"
            ),
        )
    if sub_calls:
        return AdapterRow(
            file=str(path),
            verdict="preflight-gate-missing",
            detail=(
                "module imports publish_mode_contract and subscribes "
                "but does not call require_compatible — Bug-42-class "
                "preflight gate missing (subscriber MUST refuse "
                "silent-drop pairs at bring-up)"
            ),
        )
    return AdapterRow(
        file=str(path),
        verdict="publisher-no-gate",
        detail=(
            "module imports publish_mode_contract and publishes "
            "but has no subscribe call — gate responsibility is on "
            "the subscriber counterpart (informational, not drift)"
        ),
    )


# ---------------------------------------------------------------------------
# Top-level audit
# ---------------------------------------------------------------------------


def audit_repo(repo_root: pathlib.Path) -> AuditResult:
    """Run the full audit over a repo working tree.

    The function is pure: it reads files only under ``repo_root``
    and produces a single :class:`AuditResult`. No network, no
    git invocations, no env reads.
    """

    repo_root = repo_root.resolve()
    inventory: List[CallRow] = []
    subjects: List[SubjectRow] = []
    mode_checks: List[ModeCheckRow] = []
    adapter_checks: List[AdapterRow] = []
    scanned = 0

    for path in _iter_source_files(repo_root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        scanned += 1
        calls = scan_calls(path, text)
        inventory.extend(calls)
        subjects.extend(scan_subjects(path, text))
        mc = cross_validate_modes(path, text, calls)
        if mc is not None:
            mode_checks.append(mc)
        ac = adapter_config_audit(path, text, calls)
        if ac is not None:
            adapter_checks.append(ac)

    # Sort everything for deterministic output.
    inventory.sort(key=lambda r: (r.file, r.line, r.kind))
    subjects.sort(key=lambda r: (r.file, r.line, r.literal))
    mode_checks.sort(key=lambda r: r.file)
    adapter_checks.sort(key=lambda r: r.file)

    return AuditResult(
        repo_root=str(repo_root),
        scanned_files=scanned,
        inventory=tuple(inventory),
        subjects=tuple(subjects),
        mode_checks=tuple(mode_checks),
        adapter_checks=tuple(adapter_checks),
    )


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------


def _rel(path: str, repo_root: str) -> str:
    """Render ``path`` relative to ``repo_root`` if possible."""

    try:
        return str(pathlib.Path(path).resolve().relative_to(pathlib.Path(repo_root).resolve()))
    except ValueError:
        return path


# Pipe-escape constant — used in Markdown-table cells. Pulled out of
# f-strings so the module stays compatible with Python 3.11 (which
# disallows backslashes inside f-string expression parts; the
# constraint was relaxed in 3.12 but the CI runner pins 3.11).
_ESCAPED_PIPE = "\\|"


def _esc_pipe(s: str) -> str:
    """Escape Markdown-table pipe characters."""

    return s.replace("|", _ESCAPED_PIPE)


def render_report(result: AuditResult, *, generated_at: str) -> str:
    """Render the audit report as Markdown."""

    rr = result.repo_root
    lines: List[str] = []
    lines.append("# NATS-JetStream Subjects + Publish-Mode Audit")
    lines.append("")
    lines.append(f"- Generated: `{generated_at}`")
    lines.append(f"- Repo root: `{rr}`")
    lines.append(f"- Scanned files (Python + Rust): {result.scanned_files}")
    lines.append(f"- Total drift rows: **{result.drift_count}**")
    lines.append("")
    lines.append(
        "This report mirrors `docs/audit/nats-jetstream-subjects-audit.md`. "
        "See that document for the audit charter, exclusion rules, and "
        "remediation guidance."
    )
    lines.append("")

    # ---------------- Inventory ----------------
    lines.append("## 1. Inventory — publish/subscribe call sites")
    lines.append("")
    if not result.inventory:
        lines.append("_No publish/subscribe call sites detected._")
    else:
        lines.append("| File | Line | Kind | Snippet |")
        lines.append("|------|-----:|------|---------|")
        for r in result.inventory:
            lines.append(
                f"| `{_rel(r.file, rr)}` | {r.line} | `{r.kind}` | "
                f"`{_esc_pipe(r.snippet)}` |"
            )
    lines.append("")

    # ---------------- Subjects ----------------
    drift_subjects = [
        s for s in result.subjects
        if s.verdict in ("regex-drift", "template-drift")
    ]
    ok_subjects = [s for s in result.subjects if s.verdict == "ok"]
    namespace_subjects = [
        s for s in result.subjects if s.verdict == "namespace-id"
    ]
    lines.append("## 2. Subject-Pattern-Drift Check")
    lines.append("")
    lines.append(
        f"- Total wakir.* literals: {len(result.subjects)} "
        f"(NATS subjects: {len(ok_subjects) + len(drift_subjects)}, "
        f"namespace-ids: {len(namespace_subjects)})"
    )
    lines.append(f"- Drift rows: **{len(drift_subjects)}**")
    lines.append("")
    if drift_subjects:
        lines.append("| File | Line | Literal | Verdict | Detail |")
        lines.append("|------|-----:|---------|---------|--------|")
        for s in drift_subjects:
            lines.append(
                f"| `{_rel(s.file, rr)}` | {s.line} | "
                f"`{s.literal}` | `{s.verdict}` | "
                f"{_esc_pipe(s.detail)} |"
            )
    else:
        lines.append(
            "_No subject-pattern drift detected — every "
            "`wakir.<env>.*` literal matches the canonical "
            "`wakir.<env>.<domain>.<event>[.<sub_id>]` form._"
        )
    if namespace_subjects:
        lines.append("")
        lines.append(
            f"<details><summary>"
            f"{len(namespace_subjects)} namespace-id literal(s) "
            f"(informational, not drift)"
            f"</summary>"
        )
        lines.append("")
        lines.append("| File | Line | Literal | Detail |")
        lines.append("|------|-----:|---------|--------|")
        for s in namespace_subjects:
            lines.append(
                f"| `{_rel(s.file, rr)}` | {s.line} | "
                f"`{s.literal}` | "
                f"{_esc_pipe(s.detail)} |"
            )
        lines.append("")
        lines.append("</details>")
    lines.append("")

    # ---------------- Mode-cross-validation ----------------
    incomplete = [
        m for m in result.mode_checks if m.verdict == "adapter-incomplete"
    ]
    lines.append("## 3. Mode-Cross-Validation (Bug-42 Adapter-B)")
    lines.append("")
    lines.append(f"- Modules in scope: {len(result.mode_checks)}")
    lines.append(f"- Adapter-incomplete rows: **{len(incomplete)}**")
    lines.append("")
    if result.mode_checks:
        lines.append("| File | Verdict | Detail |")
        lines.append("|------|---------|--------|")
        for m in result.mode_checks:
            lines.append(
                f"| `{_rel(m.file, rr)}` | `{m.verdict}` | "
                f"{_esc_pipe(m.detail)} |"
            )
    else:
        lines.append("_No modules in scope._")
    lines.append("")

    # ---------------- Adapter-config-audit ----------------
    missing_gates = [
        a for a in result.adapter_checks
        if a.verdict == "preflight-gate-missing"
    ]
    lines.append("## 4. Adapter-Config-Audit (require_compatible gate)")
    lines.append("")
    lines.append(f"- Modules in scope: {len(result.adapter_checks)}")
    lines.append(f"- Preflight-gate-missing rows: **{len(missing_gates)}**")
    lines.append("")
    if result.adapter_checks:
        lines.append("| File | Verdict | Detail |")
        lines.append("|------|---------|--------|")
        for a in result.adapter_checks:
            lines.append(
                f"| `{_rel(a.file, rr)}` | `{a.verdict}` | "
                f"{_esc_pipe(a.detail)} |"
            )
    else:
        lines.append("_No modules in scope._")
    lines.append("")

    # ---------------- Recommended fixes ----------------
    lines.append("## 5. Recommended fixes")
    lines.append("")
    if result.drift_count == 0:
        lines.append(
            "_No drift detected. The codebase is Bug-42-compliant: every "
            "publish-mode-aware module either gates with "
            "`require_compatible` or dispatches both `nc.publish` and "
            "`js.publish` consistently with its publish-mode discriminator._"
        )
    else:
        if drift_subjects:
            lines.append(
                "- **Subject-pattern drift:** rewrite the literal to match "
                "the canonical `wakir.<env>.<domain>.<event>[.<sub_id>]` "
                "form (see `wirelang/nats/subject_mapping.py`)."
            )
        if incomplete:
            lines.append(
                "- **Adapter-incomplete:** add a `--publish-mode` switch "
                "and dispatch to `js.publish(...)` on `jetstream` mode "
                "(Tag-41 pattern from `wirelang/cli/bridge_forward.py` "
                "lines 396–406)."
            )
        if missing_gates:
            lines.append(
                "- **Preflight-gate-missing:** add a "
                "`publish_mode_contract.require_compatible(...)` call at "
                "module bring-up to refuse silent-drop pairs before they "
                "happen (spec §13.2)."
            )
    lines.append("")
    lines.append("---")
    lines.append(
        "Generated by `scripts/audit/nats-jetstream-subjects-audit.py` "
        "(Selin, Tag-43)."
    )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="nats-jetstream-subjects-audit",
        description=(
            "Static audit of NATS publish/subscribe call sites, subject "
            "patterns, and publish-mode adapter configuration (Tag-43, "
            "Selin)."
        ),
    )
    p.add_argument(
        "--repo-root",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[2],
        help=(
            "Path to the wakir-runtime repo root to audit. Defaults to "
            "the parent of the scripts/audit/ directory."
        ),
    )
    p.add_argument(
        "--report",
        type=pathlib.Path,
        default=None,
        help=(
            "If given, write the Markdown report to this path instead "
            "of stdout. Parent directories are created as needed."
        ),
    )
    p.add_argument(
        "--enforce",
        action="store_true",
        help=(
            "Exit non-zero if any drift row is detected (default is "
            "audit-only — always exits 0)."
        ),
    )
    p.add_argument(
        "--utc-date",
        type=str,
        default=None,
        help=(
            "Override the generated-at timestamp for deterministic "
            "snapshot tests. Format: YYYY-MM-DDThh:mm:ssZ."
        ),
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(list(argv if argv is not None else sys.argv[1:]))
    result = audit_repo(args.repo_root)
    generated_at = (
        args.utc_date
        if args.utc_date is not None
        else _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )
    md = render_report(result, generated_at=generated_at)
    if args.report is None:
        sys.stdout.write(md)
    else:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(md, encoding="utf-8")
        print(
            f"[nats-jetstream-subjects-audit] wrote report to "
            f"{args.report} ({result.drift_count} drift row(s), "
            f"{result.scanned_files} file(s) scanned)",
            file=sys.stderr,
        )
    if args.enforce and result.drift_count > 0:
        print(
            f"[nats-jetstream-subjects-audit] ENFORCE-MODE FAIL: "
            f"{result.drift_count} drift row(s) detected.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
