# Test-Counts Convention (Wirelang Suite)

**Status:** Active (Phase-2 Sprint-6 Tag-5 onwards).
**Owner:** Reza Tehrani (dev-engineering-2 / wirelang).
**Scope:** `wirelang/tests/` pytest-collected test suite.
**Cross-reference:** Mira-Inbox Sprint-6 Tag-5 Item 1
(Test-Count-Discrepancy-Reconciliation).

This document codifies the canonical test-count baseline-modus
for the Wirelang suite, and resolves a reporting discrepancy
between Mira-Inbox "842 → 854 Sprint-6 Tag-1" and Reza local
report "868 → 885 Sprint-6 Tag-3".

## 1. Canonical Counter Format

Every Wirelang test-progression report MUST cite the three-tuple:

```
<passed> passed, <skipped> skipped, <subtests> subtests passed
```

Example (Sprint-6 Tag-4 tip `ece8f45`):
**`885 passed, 1 skipped, 7 subtests passed`**.

The shape of the line is determined by pytest's terminal-reporter
summary line. The `subtests passed` token appears only when at
least one `unittest.TestCase.subTest()` block executes — see §4.

## 2. Acceptance-Reference Baseline-Modus

**The canonical reference is the local worktree pytest summary
line at the tip commit, executed in a fresh worktree.**

Rationale:

- The wakir-runtime CI pipeline (if/when wired) executes pytest
  with identical configuration to the local pyproject.toml-based
  invocation; collection and execution are deterministic across
  hosts for this suite.
- "Local worktree" means a worktree created via
  `git worktree add <path> <commit>` (per ADR-0049) with the
  reza-pinned `.venv` (pytest 9.0.3, Python 3.14.4 at time of
  writing). No `--collect-only`-tricks, no stale uncommitted files.
- CI numbers SHOULD match local numbers. Any drift indicates a
  configuration leak (e.g. environment-dependent skip predicates,
  plugin-mismatch, conftest.py path-divergence) and is itself a
  bug to be filed, NOT a reporting convention.

## 3. The 842 → 854 vs. 868 → 885 Reconciliation

**No CI-vs-local discrepancy exists.** Both numbers are correct
at their respective tips; they describe DIFFERENT phases of the
Sprint-6 sequence:

| Tip       | Commit    | passed | skipped | subtests | delta |
|---        |---        |---     |---      |---       |---    |
| Sprint-5 Tag-5 | `b2ecc3e` | 842 | 1 | 7 | baseline |
| Sprint-6 Tag-1 | `e944b93` | 854 | 1 | 7 | +12 |
| Sprint-6 Tag-2 | `3516466` | 868 | 1 | 7 | +14 |
| Sprint-6 Tag-3 | `39ae824` | 885 | 1 | 7 | +17 |
| Sprint-6 Tag-4 | `ece8f45` | 885 | 1 | 7 |   0 (doc-only) |

Verified 2026-05-11T23:50–23:58 CEST via probe-worktrees at each
tip, identical Reza-`.venv` toolchain.

Interpretation:

- **Mira-Inbox "842 → 854 Sprint-6 Tag-1"** is the
  S5T5 → S6T1 transition. Correct.
- **Reza-conversations "868 → 885 Sprint-6 Tag-3"** is the
  S6T2 → S6T3 transition. Correct.
- Both reports were correct **at the time of writing**; what
  looked like a discrepancy was a baseline-pinning mismatch
  in the verbal report — different prior tips chosen as
  reference.

The Tag-1 Reza-conversations note that quoted local "838 → 852"
was a transient measurement error (uncommitted-file state or
plugin-load discrepancy at that moment; not reproducible at the
clean tip `e944b93` which reproduces 854 deterministically).

## 4. The Constant "7 subtests passed"

The Wirelang suite contains exactly **one** test that uses
`unittest.TestCase.subTest`:

- `wirelang/tests/test_aip_https_backend.py::HappyPathTests::test_max_age_parsing_robustness`
- Iterates over 7 cache-control header strings (lines 322–330
  at Sprint-6 Tag-4 tip).
- Each loop iteration enters a `with self.subTest(cc=cc):` block.

pytest reports each subTest as a separate "subtest passed" in
the summary line. Hence the constant **7 subtests passed** since
Sprint-4 Tag-4 (when the test was added; verify via
`git log --diff-filter=A -- wirelang/tests/test_aip_https_backend.py`).

This count is suite-stable until either:

- a new `with self.subTest(...)` block is added, OR
- the existing 7-case table is modified.

**The `pytest-subtests` plugin is NOT installed** (verified via
`pip list | grep subtest` at the tip `ece8f45`). The "subtests
passed" reporting is native pytest support for
`unittest.TestCase.subTest`.

## 5. Counter Verification Recipe

To verify any tip's canonical count:

```bash
cd <wakir-runtime>
git worktree add /tmp/wirelang-probe-<short-sha> <commit>
cd /tmp/wirelang-probe-<short-sha>
<reza-venv>/bin/pytest wirelang/tests/ 2>&1 | tail -3
# Read the summary line, cite as canonical
cd <wakir-runtime>
git worktree remove /tmp/wirelang-probe-<short-sha>
```

The collection-only count (`pytest --collect-only`) reports
**collected items** which equals `passed + failed + skipped`,
NOT `passed + skipped`. At Tag-4 tip `ece8f45`:
**886 items collected** = 885 + 1 (the skipped). Do not use
the collected count as the canonical pass count.

## 6. Per-Subtest Verbose Reporting

`pytest -v wirelang/tests/test_aip_https_backend.py` shows
the parent test as a single line and does NOT enumerate
sub-cases. To see per-subtest output, use:

```bash
pytest -v --tb=short wirelang/tests/test_aip_https_backend.py::HappyPathTests::test_max_age_parsing_robustness
```

The subtests are visible in the failure-output only on failure;
on success the summary remains "7 subtests passed".

## 7. Acceptance for Future Reports

From Sprint-6 Tag-5 onwards:

- Test-progression rows in done-reports cite the full three-tuple
  (passed, skipped, subtests).
- Cross-tip comparisons cite both endpoint tips with commit-sha
  and delta.
- Any number that cannot be reproduced via the §5 recipe at the
  cited tip is to be treated as a transient measurement error
  and corrected in the next done-report.

## 8. Change-Log

- **2026-05-11 (Sprint-6 Tag-5)** Document created. Reconciliation
  of the Tag-1 Mira-Inbox vs. Tag-3 Reza-report quote-mismatch.
  Owner: Reza Tehrani.

— Reza
