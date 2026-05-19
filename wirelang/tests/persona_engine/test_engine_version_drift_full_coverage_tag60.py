# SPDX-License-Identifier: BUSL-1.1
# Copyright (c) 2026 Callandor GmbH and contributors
"""Tag-60 — Engine-Version-Drift FULL coverage pin (Selin, Persona-Engine).

Trigger event
-------------
Mira's Hot-Fix #381 on Tag-59 had to sweep four drift layers after the
Tag-58 0.5.3-rc1 bump escaped the existing
``test_engine_0_5_3_rc1_release_notes_tag58.py`` net:

(a) ``wirelang/persona_engine/engine_async.py`` line 96 still carried
    ``ASYNC_ENGINE_VERSION = "0.5.0-pilot"`` (now 0.5.3-rc1).
(b) ``wirelang/persona_engine/cli.py`` line 3 docstring still said
    ``"CLI entry points for ``persona-engine`` (v0.5.0-pilot)."``.
(c) Seven hermetic test files carried hardcoded ``"0.5.0-pilot"``
    fixtures that were silently outdated.
(d) The prior-art release-notes pin (Tag-58) only asserted byte-shape
    on ``__version__.py`` + ``__init__.py`` + ``engine.py``. It did
    NOT scan ``engine_async.py`` or ``cli.py``, and did NOT scan the
    test corpus for hardcoded stale literals.

Tag-60 closes (a)..(d) with a single hermetic scanner
(``tooling/ci/scan_engine_version_drift.py``) plus a JSON allowlist
(``tooling/ci/engine-version-drift-allowlist.json``) for the
legitimate stale-literal contexts (frozen manifests, migration
contracts, V-907 hash-baseline inputs).

What this test pins
-------------------
* The scanner module imports cleanly and exposes the expected public
  API surface.
* The active version constant matches ``__version__.__version__``.
* The hunt set is exactly the documented Tag-58/59/62 trigger literals.
* Scan globs cover engine_async.py + cli.py + every persona_engine
  module + every persona_engine test (the four surfaces the Tag-58
  prior-art missed).
* The allowlist parses, has the schema expected, and covers exactly
  the historical surfaces — no entry is unused.
* A full repo scan finds zero un-allowlisted drift findings.
* The scanner correctly flags a synthetic drift in a tmp-dir mini-repo
  (positive control).
* The scanner skips an allowlisted synthetic drift (negative control).
* The CLI exit-code contract is 0 / 1 / 2 per the documented protocol.

Hermetic envelope
-----------------
* No network. No NATS, no SPIRE, no gRPC.
* No subprocess outside of ``python -c`` against the scanner module
  for CLI-shape probes (a clean stdlib import + main() call).
* Pure file inspection of the repo under test.

Scope discipline (Selin)
------------------------
This test does NOT modify persona definitions (Aisha-Domaene,
ADR-0043), WAT-core logic (Tomas-Domaene, Zone-K), identity-substrate
design (Reza-Domaene, Zone-L), or container-infra (Kai-Domaene,
Zone-J).

Negative-assertion fixtures (used by the synthetic-drift positive
control test — these strings are intentionally present here so the
scanner-on-itself path exercises the allowlist):

    FIXTURE_STALE_LITERALS = ("0.5.0-pilot", "0.5.1-pre-cutover",
                              "0.5.2-final-pre-cutover", "0.5.3-rc1")

Tag-62 (2026-05-19, Selin) added ``0.5.3-rc1`` to the hunted set
when the rc1-suffix-drop final-bump promoted ``0.5.3`` to active.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout
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

# The four trigger literals (used by the synthetic-drift positive
# control). Verbatim string declaration — the scanner's allowlist
# entry for this test file legitimises their presence. Tag-62 added
# 0.5.3-rc1 to the hunted set after the rc1-suffix-drop final-bump.
FIXTURE_STALE_LITERALS = (
    "0.5.0-pilot",
    "0.5.1-pre-cutover",
    "0.5.2-final-pre-cutover",
    "0.5.3-rc1",
)


# ---------------------------------------------------------------------------
# Scanner module loader. We import-by-path rather than via the package
# namespace because ``tooling/`` is not under any importable package
# root in the persona-engine wheel — it is a CI helper tree.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def scanner_module():
    spec = importlib.util.spec_from_file_location(
        "scan_engine_version_drift_tag60_fixture", SCANNER_PATH
    )
    assert spec is not None and spec.loader is not None, (
        f"unable to load scanner spec from {SCANNER_PATH}"
    )
    module = importlib.util.module_from_spec(spec)
    # Python 3.14 dataclass-resolver requires the module to be visible
    # in sys.modules before exec_module so dataclasses with string
    # annotations can look up their own module's namespace.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def allowlist_data() -> dict:
    return json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tests.
# ---------------------------------------------------------------------------


def test_01_scanner_module_loads_and_exports_public_api(scanner_module) -> None:
    """The scanner exposes the documented public surface."""
    expected_attrs = {
        "ACTIVE_VERSION",
        "STALE_VERSIONS",
        "SCAN_GLOBS",
        "LEGITIMATE_CATEGORIES",
        "DEFAULT_ALLOWLIST_RELPATH",
        "Finding",
        "AllowlistEntry",
        "ScanResult",
        "AllowlistError",
        "load_allowlist",
        "iter_scan_files",
        "scan_file",
        "scan_repo",
        "main",
    }
    missing = expected_attrs - set(dir(scanner_module))
    assert not missing, f"scanner module missing public API: {missing}"


def test_02_active_version_matches_canonical_version_module(
    scanner_module,
) -> None:
    """The scanner's ``ACTIVE_VERSION`` mirrors ``__version__.py``."""
    spec = importlib.util.spec_from_file_location(
        "persona_engine_version_tag60_fixture",
        REPO_ROOT / "wirelang" / "persona_engine" / "__version__.py",
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    assert scanner_module.ACTIVE_VERSION == mod.__version__, (
        f"scanner ACTIVE_VERSION={scanner_module.ACTIVE_VERSION!r} != "
        f"__version__={mod.__version__!r}"
    )


def test_03_stale_versions_is_exactly_three_trigger_literals(
    scanner_module,
) -> None:
    """The hunt set is exactly the documented Tag-58/59 trigger literals.

    Function name preserved across Tag-62 for test-id stability;
    the hunt set is now four literals (rc1 added at Tag-62) but the
    invariant — STALE_VERSIONS mirrors FIXTURE_STALE_LITERALS — is
    unchanged.
    """
    assert set(scanner_module.STALE_VERSIONS) == set(FIXTURE_STALE_LITERALS), (
        "STALE_VERSIONS drifted from the documented trigger set"
    )
    # Ordering invariant: longest-first to make substring overlap
    # deterministic for future literal additions.
    assert list(scanner_module.STALE_VERSIONS) == sorted(
        scanner_module.STALE_VERSIONS, key=len, reverse=True
    ), "STALE_VERSIONS must be sorted longest-first"


def test_04_scan_globs_cover_engine_async_and_cli(scanner_module) -> None:
    """Scan globs reach the two surfaces the Tag-58 prior-art missed."""
    globs = list(scanner_module.SCAN_GLOBS)
    # The persona_engine *.py glob is the umbrella that includes
    # engine_async.py and cli.py.
    assert any(
        g.endswith("persona_engine/*.py") for g in globs
    ), f"missing persona_engine/*.py glob: {globs}"
    # Materialise the glob and confirm both files are reached.
    matches = list(scanner_module.iter_scan_files(REPO_ROOT))
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in matches}
    for must_have in (
        "wirelang/persona_engine/engine_async.py",
        "wirelang/persona_engine/cli.py",
    ):
        assert must_have in rels, (
            f"scan globs do not reach {must_have} (the Tag-59 hot-fix "
            "drift surfaces)"
        )


def test_05_scan_globs_cover_persona_engine_test_corpus(scanner_module) -> None:
    """Scan globs reach the test corpus the Tag-58 prior-art missed."""
    matches = list(scanner_module.iter_scan_files(REPO_ROOT))
    rels = {p.relative_to(REPO_ROOT).as_posix() for p in matches}
    test_hits = {r for r in rels if r.startswith("wirelang/tests/persona_engine/")}
    # The Tag-58 hot-fix had to touch seven hardcoded-literal test files;
    # the scanner must see at least that many tests under the glob.
    assert len(test_hits) >= 7, (
        f"scan-globs reach only {len(test_hits)} persona_engine tests; "
        "Tag-59 hot-fix #381 had to sweep seven test files"
    )


def test_06_allowlist_parses_under_strict_schema(scanner_module) -> None:
    """The allowlist is well-formed against the scanner's strict schema."""
    parsed = scanner_module.load_allowlist(ALLOWLIST_PATH)
    assert parsed, "allowlist parsed to an empty dict"
    # Every entry has a non-empty categories tuple drawn from the
    # legitimate set, and a non-empty reason.
    for path, entry in parsed.items():
        assert entry.categories, f"empty categories on {path}"
        assert set(entry.categories) <= scanner_module.LEGITIMATE_CATEGORIES, (
            f"illegal categories on {path}: {entry.categories}"
        )
        assert entry.reason.strip(), f"empty reason on {path}"


def test_07_allowlist_includes_engine_async_is_NOT_present_active_code(
    scanner_module, allowlist_data
) -> None:
    """``engine_async.py`` MUST NOT be on the allowlist.

    The Tag-59 hot-fix scrubbed the stale ``ASYNC_ENGINE_VERSION``
    literal from this file. The scanner is the guard that the file
    stays clean — adding it to the allowlist would re-open the gap.
    """
    paths = {e["path"] for e in allowlist_data["entries"]}
    assert "wirelang/persona_engine/engine_async.py" not in paths, (
        "engine_async.py must not be allowlisted — the scanner is the "
        "guard that it stays clean of stale literals"
    )


def test_08_allowlist_includes_cli_is_NOT_present_active_code(
    scanner_module, allowlist_data
) -> None:
    """``cli.py`` MUST NOT be on the allowlist (same rationale as engine_async)."""
    paths = {e["path"] for e in allowlist_data["entries"]}
    assert "wirelang/persona_engine/cli.py" not in paths, (
        "cli.py must not be allowlisted — the scanner is the guard "
        "that the docstring stays in lockstep with the version bump"
    )


def test_09_repo_scan_is_clean_under_default_allowlist(scanner_module) -> None:
    """A fresh scan of the repo finds zero un-allowlisted drift."""
    allowlist = scanner_module.load_allowlist(ALLOWLIST_PATH)
    result = scanner_module.scan_repo(REPO_ROOT, allowlist)
    assert not result.findings, (
        f"un-allowlisted drift on main: "
        f"{[f.as_record() for f in result.findings]}"
    )


def test_10_scan_file_engine_async_returns_no_stale_literals(
    scanner_module,
) -> None:
    """``engine_async.py`` carries no stale version literal."""
    hits = scanner_module.scan_file(
        REPO_ROOT / "wirelang" / "persona_engine" / "engine_async.py",
        REPO_ROOT,
    )
    assert hits == [], (
        f"engine_async.py carries stale literals: "
        f"{[h.as_record() for h in hits]}"
    )


def test_11_scan_file_cli_docstring_returns_no_stale_literals(
    scanner_module,
) -> None:
    """``cli.py`` docstring carries no stale version literal."""
    hits = scanner_module.scan_file(
        REPO_ROOT / "wirelang" / "persona_engine" / "cli.py", REPO_ROOT
    )
    assert hits == [], (
        f"cli.py carries stale literals: {[h.as_record() for h in hits]}"
    )


def test_12_scan_file_positive_control_synthetic_drift(
    scanner_module, tmp_path
) -> None:
    """Synthetic drift in a tmp-dir mini-repo is correctly flagged."""
    fake_root = tmp_path / "minirepo"
    pkg = fake_root / "wirelang" / "persona_engine"
    pkg.mkdir(parents=True)
    drifty = pkg / "engine_drifty.py"
    drifty.write_text(
        'ENGINE_VERSION = "0.5.0-pilot"\n'
        '# fallback ladder includes 0.5.1-pre-cutover stages\n',
        encoding="utf-8",
    )
    hits = scanner_module.scan_file(drifty, fake_root)
    literals = {h.literal for h in hits}
    assert "0.5.0-pilot" in literals
    assert "0.5.1-pre-cutover" in literals
    assert all(
        h.path == "wirelang/persona_engine/engine_drifty.py" for h in hits
    )


def test_13_scan_repo_positive_control_unallowlisted_drift(
    scanner_module, tmp_path
) -> None:
    """An empty allowlist on a drifty mini-repo produces un-allowlisted findings."""
    fake_root = tmp_path / "minirepo"
    pkg = fake_root / "wirelang" / "persona_engine"
    pkg.mkdir(parents=True)
    (pkg / "drift.py").write_text(
        '__version__ = "0.5.2-final-pre-cutover"\n', encoding="utf-8"
    )
    result = scanner_module.scan_repo(fake_root, allowlist={})
    assert result.findings, "scan_repo missed an obvious drift literal"
    assert not result.allowlisted


def test_14_scan_repo_negative_control_allowlisted_drift(
    scanner_module, tmp_path
) -> None:
    """A drifty file on the allowlist lands in ``.allowlisted``, not ``.findings``."""
    fake_root = tmp_path / "minirepo"
    pkg = fake_root / "wirelang" / "persona_engine"
    pkg.mkdir(parents=True)
    (pkg / "frozen_manifest.py").write_text(
        '# Historical manifest reference to 0.5.0-pilot.\n',
        encoding="utf-8",
    )
    allowlist = {
        "wirelang/persona_engine/frozen_manifest.py": scanner_module.AllowlistEntry(
            path="wirelang/persona_engine/frozen_manifest.py",
            categories=("historical-manifest",),
            reason="synthetic test fixture",
        )
    }
    result = scanner_module.scan_repo(fake_root, allowlist=allowlist)
    assert not result.findings
    assert result.allowlisted, "allowlisted hit was not classified correctly"


def test_15_allowlist_rejects_unknown_category(
    scanner_module, tmp_path
) -> None:
    """Unknown categories trigger ``AllowlistError`` — no silent suppression."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "path": "x.py",
                        "categories": ["not-a-real-category"],
                        "reason": "test",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(scanner_module.AllowlistError):
        scanner_module.load_allowlist(bad)


def test_16_allowlist_rejects_empty_categories(
    scanner_module, tmp_path
) -> None:
    """Empty categories lists are a schema violation."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {"entries": [{"path": "x.py", "categories": [], "reason": "t"}]}
        ),
        encoding="utf-8",
    )
    with pytest.raises(scanner_module.AllowlistError):
        scanner_module.load_allowlist(bad)


def test_17_allowlist_rejects_duplicate_path(scanner_module, tmp_path) -> None:
    """Duplicate path entries are a schema violation."""
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "path": "x.py",
                        "categories": ["historical-manifest"],
                        "reason": "a",
                    },
                    {
                        "path": "x.py",
                        "categories": ["historical-manifest"],
                        "reason": "b",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(scanner_module.AllowlistError):
        scanner_module.load_allowlist(bad)


def test_18_cli_exit_code_zero_on_clean_repo(scanner_module) -> None:
    """``main()`` returns 0 when no un-allowlisted findings exist."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = scanner_module.main(
            [
                "--repo-root",
                str(REPO_ROOT),
                "--allowlist",
                str(ALLOWLIST_PATH),
            ]
        )
    assert rc == 0, f"CLI returned {rc} on clean repo. Output: {buf.getvalue()}"


def test_19_cli_exit_code_one_on_unallowlisted_drift(
    scanner_module, tmp_path
) -> None:
    """``main()`` returns 1 when a drift escapes the allowlist."""
    fake_root = tmp_path / "minirepo"
    pkg = fake_root / "wirelang" / "persona_engine"
    pkg.mkdir(parents=True)
    (pkg / "drifty.py").write_text(
        '__version__ = "0.5.0-pilot"\n', encoding="utf-8"
    )
    empty_allowlist = tmp_path / "allow.json"
    empty_allowlist.write_text(json.dumps({"entries": []}), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = scanner_module.main(
            [
                "--repo-root",
                str(fake_root),
                "--allowlist",
                str(empty_allowlist),
            ]
        )
    assert rc == 1, f"CLI returned {rc} on drifty repo. Output: {buf.getvalue()}"


def test_20_cli_exit_code_two_on_invariant_violation(
    scanner_module, tmp_path
) -> None:
    """``main()`` returns 2 when the allowlist is malformed."""
    bad_allow = tmp_path / "bad.json"
    bad_allow.write_text("{not json", encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = scanner_module.main(
            [
                "--repo-root",
                str(REPO_ROOT),
                "--allowlist",
                str(bad_allow),
            ]
        )
    assert rc == 2, f"CLI returned {rc} on bad allowlist; expected 2"


def test_21_cli_strict_mode_flags_allowlisted_hits(
    scanner_module, tmp_path
) -> None:
    """``--strict`` returns 1 even when every finding is allowlisted."""
    fake_root = tmp_path / "minirepo"
    pkg = fake_root / "wirelang" / "persona_engine"
    pkg.mkdir(parents=True)
    (pkg / "frozen.py").write_text(
        '# 0.5.0-pilot historical reference\n', encoding="utf-8"
    )
    allow = tmp_path / "allow.json"
    allow.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "path": "wirelang/persona_engine/frozen.py",
                        "categories": ["historical-manifest"],
                        "reason": "test fixture",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = scanner_module.main(
            [
                "--repo-root",
                str(fake_root),
                "--allowlist",
                str(allow),
                "--strict",
            ]
        )
    assert rc == 1, (
        f"--strict should return 1 on allowlisted-only findings, got {rc}"
    )


def test_22_finding_record_is_byte_shape_stable(scanner_module) -> None:
    """``Finding.as_record`` produces a deterministic, JSON-serialisable dict."""
    f = scanner_module.Finding(
        path="x.py", line=1, col=2, literal="0.5.0-pilot", line_text="abc"
    )
    record = f.as_record()
    assert record == {
        "path": "x.py",
        "line": 1,
        "col": 2,
        "literal": "0.5.0-pilot",
        "line_text": "abc",
    }
    # Round-trip through json.dumps to confirm it is fully serialisable.
    json.dumps(record)


def test_23_allowlist_entry_unused_does_not_exist(
    scanner_module, allowlist_data
) -> None:
    """Every allowlist path either has scan hits OR is the scanner's self-test fixture.

    A presumed-unused allowlist entry is a code-smell — it widens the
    suppression surface without need. The Tag-60 allowlist is curated
    so that every entry corresponds to either (a) a real file with
    legitimate stale literals or (b) the scanner's own test fixture
    file (which lists fixture literals for the positive-control test).
    """
    allowlist = scanner_module.load_allowlist(ALLOWLIST_PATH)
    self_test_path = (
        "wirelang/tests/persona_engine/"
        "test_engine_version_drift_full_coverage_tag60.py"
    )
    for path, entry in allowlist.items():
        if path == self_test_path:
            # The self-test fixture file always has hits (FIXTURE_STALE_LITERALS).
            continue
        abs_path = REPO_ROOT / path
        assert abs_path.is_file(), (
            f"allowlist entry references non-existent path: {path}"
        )
        hits = scanner_module.scan_file(abs_path, REPO_ROOT)
        assert hits, (
            f"allowlist entry for {path} has no scan hits — entry is "
            "unused and widens the suppression surface without need"
        )


def test_24_scanner_does_not_flag_active_version(
    scanner_module, tmp_path
) -> None:
    """The active version literal is never reported as a drift finding."""
    fake_root = tmp_path / "minirepo"
    pkg = fake_root / "wirelang" / "persona_engine"
    pkg.mkdir(parents=True)
    (pkg / "current.py").write_text(
        f'__version__ = "{scanner_module.ACTIVE_VERSION}"\n',
        encoding="utf-8",
    )
    result = scanner_module.scan_repo(fake_root, allowlist={})
    assert not result.findings, (
        f"scanner flagged the active version {scanner_module.ACTIVE_VERSION!r} "
        "— hunt-set must be stale-only"
    )


def test_25_iter_scan_files_is_deterministic(scanner_module) -> None:
    """Two consecutive walks of the same repo return identical paths."""
    first = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in scanner_module.iter_scan_files(REPO_ROOT)
    ]
    second = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in scanner_module.iter_scan_files(REPO_ROOT)
    ]
    assert first == second, (
        "iter_scan_files is non-deterministic — that defeats CI reproducibility"
    )
