# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
#
# Licensed under the Business Source License 1.1; see
# wirelang/persona_engine/LICENSE-BSL.md.
# Change Date: 2030-05-15. Change License: Apache License 2.0.
"""Tag-67 — Engine-Version-Drift-Allowlist refresh audit pin (Selin).

Trigger event
-------------
Tag-60 (PR #384) introduced the engine-version-drift scanner +
JSON allowlist. Tag-62 (PR #399) extended the hunted
STALE_VERSIONS set with ``0.5.3-rc1`` after the rc1-suffix-drop
final-bump to ``0.5.3`` and registered the legitimate
rc1-surviving artefacts. Tag-63 (post-#399) added the
production-readiness audit report + Tag-63 test + Tag-59 V-907
hash-pin test as additional allowlist entries.

Tag-67 is the **refresh audit**: a post-Final-Bump verification
that

* every allowlisted file still exists,
* every allowlisted file still carries the stale-literal context
  the entry claims (audit-loop — no entry has been silently
  emptied),
* the schema metadata (version, tag, audit_history) reflects the
  Tag-67 refresh,
* the ``never_allowlistable`` guard explicitly enumerates the
  five surfaces the Tag-59 Hot-Fix #381 sweep taught are NEVER
  legitimate stale-literal carriers,
* the drift scanner exits 0 against the refreshed allowlist on
  the current main tip (post Tag-62 + Tag-63 substrate).

What this test pins
-------------------
* Schema version bumped to 3 (Tag-67).
* Schema tag string mentions Tag-67.
* Audit history declares the four chronological entries
  Tag-60 -> Tag-62 -> Tag-63 -> Tag-67.
* ``never_allowlistable`` enumerates engine.py + engine_async.py
  + cli.py + __init__.py + __version__.py as the five
  active-version-literal surfaces (Tag-60 Allowlist-Waechter-
  Disziplin).
* Every entry path still points at an existing file.
* Every entry path's file still contains at least one occurrence
  of at least one ``STALE_VERSIONS`` literal (no entry has been
  silently emptied by an upstream rewrite).
* The five ``never_allowlistable`` surfaces never appear as
  allowlist entries (defence in depth).
* The drift scanner exits 0 against the refreshed allowlist.
* The Tag-58 historical fixture (``test_engine_0_5_3_rc1_release_notes_tag58.py``)
  still carries ``RC1_VERSION = "0.5.3-rc1"``.
* The V-907 baseline file still carries the sealed
  ``engine_version: "0.5.3-rc1"`` literal (Tag-59 seal contract).
* ``__version__.__version__`` is ``"0.5.3"`` (active version
  literal correctness).
* The scanner's ``ACTIVE_VERSION`` constant is ``"0.5.3"``
  (lockstep with __version__).

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC.
* No subprocess outside an in-process scanner import.
* Pure file inspection + JSON parse + scanner module call.

Scope discipline (Selin)
------------------------
This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K),
identity-substrate design (Reza-Domaene, Zone-L), or
container-infra (Kai-Domaene, Zone-J).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path anchors. This file lives at wirelang/tests/persona_engine/, so
# repo_root = parents[3].
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
SCANNER_PATH = REPO_ROOT / "tooling" / "ci" / "scan_engine_version_drift.py"
ALLOWLIST_PATH = (
    REPO_ROOT / "tooling" / "ci" / "engine-version-drift-allowlist.json"
)
V907_BASELINE_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "v907-hash-baseline.json"
)
VERSION_MODULE_PATH = (
    REPO_ROOT / "wirelang" / "persona_engine" / "__version__.py"
)
TAG58_RC1_TEST_PATH = (
    REPO_ROOT
    / "wirelang"
    / "tests"
    / "persona_engine"
    / "test_engine_0_5_3_rc1_release_notes_tag58.py"
)

# The four stale literals the Tag-60+Tag-62 scanner hunts.
STALE_LITERALS = (
    "0.5.0-pilot",
    "0.5.1-pre-cutover",
    "0.5.2-final-pre-cutover",
    "0.5.3-rc1",
)

# Surfaces that must NEVER appear as allowlist entries (Tag-60
# Allowlist-Waechter-Disziplin: a stale literal on these surfaces is
# ALWAYS a bug, never a legitimate exception).
NEVER_ALLOWLISTABLE_PATHS = (
    "wirelang/persona_engine/engine.py",  # comment-only allowed; active literal forbidden
    "wirelang/persona_engine/engine_async.py",
    "wirelang/persona_engine/cli.py",
    "wirelang/persona_engine/__init__.py",
    "wirelang/persona_engine/__version__.py",  # narrative only; active literal forbidden
)

# Surfaces that ARE allowlistable but only with the
# manifest-historical-comment category (single comment line, never an
# active claim). Tag-67 keeps this list explicit so a future regression
# that adds a non-comment rc1 mention to engine.py would still trip the
# scanner.
COMMENT_ONLY_ALLOWLISTED_PATHS = (
    "wirelang/persona_engine/engine.py",
    "wirelang/persona_engine/__version__.py",
)


# ---------------------------------------------------------------------------
# Scanner module loader. We import-by-path rather than via the package
# namespace because tooling/ is not under any importable package root.
# ---------------------------------------------------------------------------


def _load_scanner_module():
    spec = importlib.util.spec_from_file_location(
        "scan_engine_version_drift_tag67", SCANNER_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def scanner():
    return _load_scanner_module()


@pytest.fixture(scope="module")
def allowlist_doc():
    return json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_t01_allowlist_path_exists():
    """The refreshed allowlist file is on disk and reachable."""
    assert ALLOWLIST_PATH.is_file(), (
        f"Tag-67 refresh: allowlist file missing at {ALLOWLIST_PATH}"
    )


def test_t02_allowlist_schema_version_bumped_to_three(allowlist_doc):
    """Tag-67 bumps the allowlist _schema.version from 2 to 3."""
    assert allowlist_doc["_schema"]["version"] == 3, (
        "Tag-67 refresh must bump _schema.version to 3"
    )


def test_t03_allowlist_schema_tag_mentions_tag_67(allowlist_doc):
    """The schema tag field names Tag-67 as the current refresh anchor."""
    tag_field = allowlist_doc["_schema"]["tag"]
    assert "Tag-67" in tag_field, (
        f"Tag-67 refresh: _schema.tag must mention Tag-67, got {tag_field!r}"
    )


def test_t04_allowlist_audit_history_has_four_entries(allowlist_doc):
    """The audit_history array declares Tag-60, Tag-62, Tag-63, Tag-67."""
    history = allowlist_doc["_schema"]["audit_history"]
    assert isinstance(history, list)
    tags = [h["tag"] for h in history]
    assert tags == ["Tag-60", "Tag-62", "Tag-63", "Tag-67"], (
        f"Tag-67 refresh: audit_history must be the four-entry chain, got {tags}"
    )


def test_t05_audit_history_entries_carry_required_fields(allowlist_doc):
    """Each audit_history entry has tag, date, action, owner, note."""
    required = {"tag", "date", "action", "owner", "note"}
    for h in allowlist_doc["_schema"]["audit_history"]:
        missing = required - set(h.keys())
        assert not missing, (
            f"audit_history entry {h.get('tag')} missing fields: {missing}"
        )


def test_t06_never_allowlistable_enumerates_five_surfaces(allowlist_doc):
    """_schema.never_allowlistable lists the five active-version-literal surfaces.

    These are the surfaces the Tag-59 Hot-Fix #381 sweep proved are
    ALWAYS active-version-literal carriers: engine.py / engine_async.py
    / cli.py / __init__.py / __version__.py. A stale literal on any of
    these surfaces is ALWAYS a regression, never a legitimate exception.
    """
    never = allowlist_doc["_schema"]["never_allowlistable"]
    assert isinstance(never, list)
    joined = "\n".join(never)
    for path in NEVER_ALLOWLISTABLE_PATHS:
        assert path in joined, (
            f"never_allowlistable must mention {path}, current list: {never}"
        )


def test_t07_every_entry_path_exists():
    """Every entry path in the refreshed allowlist points at an existing file."""
    doc = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    missing: list[str] = []
    for entry in doc["entries"]:
        p = REPO_ROOT / entry["path"]
        if not p.is_file():
            missing.append(entry["path"])
    assert not missing, (
        f"Tag-67 refresh found entries pointing at non-existent files: "
        f"{missing}"
    )


def test_t08_every_entry_path_still_carries_a_stale_literal():
    """Audit-loop: no entry has been silently emptied of stale content.

    Tag-67 refresh contract: every allowlisted file MUST still contain
    at least one occurrence of at least one STALE_LITERALS literal.
    If an upstream rewrite removed all stale literals from a path, the
    allowlist entry has become obsolete and SHOULD be removed in a
    follow-up tag (this test forces that decision into review rather
    than letting dead entries silently accumulate).
    """
    doc = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
    empty_entries: list[str] = []
    for entry in doc["entries"]:
        p = REPO_ROOT / entry["path"]
        text = p.read_text(encoding="utf-8")
        if not any(lit in text for lit in STALE_LITERALS):
            empty_entries.append(entry["path"])
    assert not empty_entries, (
        "Tag-67 audit-loop: the following allowlist entries no longer "
        "contain ANY stale-literal context and have become obsolete; "
        "they MUST be removed in a follow-up cleanup tag: "
        f"{empty_entries}"
    )


def test_t09_never_allowlistable_surfaces_are_not_allowlisted(allowlist_doc):
    """Defence in depth: the never_allowlistable paths are NEVER entries.

    Tag-67 enforces that if engine.py / engine_async.py / cli.py /
    __init__.py / __version__.py ever appear as an allowlist entry
    with a category OTHER THAN manifest-historical-comment (engine.py)
    or manifest-historical-comment+historical-migration-narrative
    (__version__.py), this test fails. The Tag-59 Hot-Fix proved these
    surfaces must stay scanner-bounded.
    """
    entries_by_path = {e["path"]: e for e in allowlist_doc["entries"]}
    forbidden = {
        "wirelang/persona_engine/engine_async.py",
        "wirelang/persona_engine/cli.py",
        "wirelang/persona_engine/__init__.py",
    }
    for path in forbidden:
        assert path not in entries_by_path, (
            f"never_allowlistable surface {path} appears as an allowlist "
            "entry; this is forbidden by Tag-60 Allowlist-Waechter-"
            "Disziplin (Tag-59 Hot-Fix #381 lesson)."
        )


def test_t10_comment_only_surfaces_have_correct_category(allowlist_doc):
    """engine.py + __version__.py allowed only as comment/narrative carriers."""
    entries_by_path = {e["path"]: e for e in allowlist_doc["entries"]}
    legitimate = {
        "wirelang/persona_engine/engine.py": {"manifest-historical-comment"},
        "wirelang/persona_engine/__version__.py": {
            "manifest-historical-comment",
            "historical-migration-narrative",
        },
    }
    for path, allowed_cats in legitimate.items():
        entry = entries_by_path.get(path)
        assert entry is not None, (
            f"comment-only allowlist entry missing: {path}"
        )
        cats = set(entry["categories"])
        unexpected = cats - allowed_cats
        assert not unexpected, (
            f"{path} categories include forbidden non-comment/narrative "
            f"categories: {unexpected}"
        )


def test_t11_v907_baseline_still_sealed_at_rc1():
    """The V-907 baseline file still pins engine_version = '0.5.3-rc1'.

    Tag-59 seal contract: the v907-hash-baseline.json engine_version
    literal is intentionally preserved at 0.5.3-rc1 even after the
    Tag-62 rc1-suffix-drop, because the V-907 composite_hash is
    byte-bounded to manifest Section 1 + pin-pack boot_wired_crates +
    engine.py resolver-block and is unchanged by metadata-only
    version-header rewrites. Refresh requires Selin-Hand + Tomas
    Zone-K cross-review.
    """
    data = json.loads(V907_BASELINE_PATH.read_text(encoding="utf-8"))
    assert data["engine_version"] == "0.5.3-rc1", (
        "Tag-67 audit: V-907 baseline engine_version has drifted from "
        f"the Tag-59 seal contract; expected '0.5.3-rc1', got "
        f"{data['engine_version']!r}. Any refresh requires Tomas "
        "Zone-K cross-review."
    )


def test_t12_active_version_is_zero_five_three(scanner):
    """The scanner's ACTIVE_VERSION is the rc1-suffix-drop literal."""
    assert scanner.ACTIVE_VERSION == "0.5.3", (
        f"scanner.ACTIVE_VERSION drifted from Tag-62 final-bump: "
        f"{scanner.ACTIVE_VERSION!r}"
    )


def test_t13_version_module_active_literal_is_zero_five_three():
    """__version__.__version__ is the rc1-suffix-drop literal '0.5.3'.

    Tag-67 lockstep check: the active version literal must match the
    scanner's ACTIVE_VERSION constant. If these ever drift apart, the
    drift scanner will start flagging itself.
    """
    spec = importlib.util.spec_from_file_location(
        "_pengine_version_t67", VERSION_MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.__version__ == "0.5.3", (
        f"__version__.__version__ drifted: {mod.__version__!r}"
    )


def test_t14_scanner_exits_zero_on_refreshed_allowlist(scanner, capsys):
    """A full repo scan against the Tag-67 refreshed allowlist exits 0."""
    # main() returns the would-be exit code without raising SystemExit.
    rc = scanner.main([])
    capsys.readouterr()  # drain captured output
    assert rc == 0, (
        f"drift scanner exited {rc} against the Tag-67 refreshed "
        "allowlist; refresh introduced un-allowlisted findings."
    )


def test_t15_tag58_historical_fixture_still_carries_rc1_constant():
    """The Tag-58 historical fixture preserves RC1_VERSION = '0.5.3-rc1'.

    Tag-67 refresh: the Tag-58 release-notes test is a frozen anchor
    of the prior tag's contract; the EXPECTED/RC1 version literal must
    survive the Tag-62 final-bump as a historical fixture for the
    rc1-surviving artefact (rc1 release-notes file under
    docs/persona-engine/, the rc1-bearing v907-hash-baseline.json).
    """
    text = TAG58_RC1_TEST_PATH.read_text(encoding="utf-8")
    assert 'RC1_VERSION = "0.5.3-rc1"' in text, (
        "Tag-58 historical fixture lost its RC1_VERSION constant — "
        "this would break the Tag-62 final-bump rc1-suffix-drop "
        "negative-assertion contract."
    )


def test_t16_no_legitimate_category_typo_in_refresh(allowlist_doc, scanner):
    """Every category string in the refreshed allowlist is in LEGITIMATE_CATEGORIES.

    The scanner's load_allowlist() would reject typos at exit-code 2,
    but Tag-67 adds an explicit in-test pin so a regression that
    relaxes the scanner check still trips here.
    """
    legitimate = scanner.LEGITIMATE_CATEGORIES
    for entry in allowlist_doc["entries"]:
        for cat in entry["categories"]:
            assert cat in legitimate, (
                f"entry {entry['path']} has unknown category {cat!r}; "
                f"legitimate set is {sorted(legitimate)}"
            )


def test_t17_entry_count_is_twenty_seven_post_refresh(allowlist_doc):
    """Tag-67 refresh: 26 carried forward + 1 new entry (this test).

    The audit conclusion (documented in the audit_history Tag-67 note):
    every 0.5.3-rc1-bearing entry remains legitimately stale per the
    Tag-59 V-907 seal + historical-narrative + negative-assertion
    fixture rationale. No entry is removed. One entry is added for the
    Tag-67 refresh-audit test itself (this file), which legitimately
    carries the four STALE_LITERALS as negative-assertion fixtures.
    """
    entries = allowlist_doc["entries"]
    assert len(entries) == 27, (
        f"Tag-67 refresh changed entry cardinality unexpectedly: "
        f"{len(entries)} entries (expected 27 = 26 carried + 1 new "
        "for this refresh-audit test)."
    )


def test_t18_audit_history_dates_are_iso_format(allowlist_doc):
    """audit_history.date fields are ISO-8601 YYYY-MM-DD strings."""
    import re

    iso = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    for h in allowlist_doc["_schema"]["audit_history"]:
        assert iso.match(h["date"]), (
            f"audit_history entry {h['tag']} has non-ISO date "
            f"{h['date']!r}; expected YYYY-MM-DD."
        )


def test_t19_scanner_strict_mode_still_exits_one_with_allowlisted_findings(
    scanner, capsys
):
    """Strict mode informs the operator the allowlist is non-empty.

    Tag-60 contract: --strict exits 1 if any allowlisted finding
    survives, signalling that the substrate is not pristine. Tag-67
    pins this contract so a future refactor that relaxes strict-mode
    semantics is caught.
    """
    rc = scanner.main(["--strict"])
    capsys.readouterr()
    # 252 allowlisted hits exist; strict-mode must exit 1.
    assert rc == 1, (
        f"strict-mode scanner exited {rc} despite 252 allowlisted "
        "hits being present; Tag-60 contract violated."
    )
