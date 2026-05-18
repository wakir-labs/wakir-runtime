#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2026 Callandor GmbH and contributors
"""Aggregator-Failure-Rate-Tracker (ADR-0068 Observability, Tag-38).

Context
-------

ADR-0068 (approved 2026-05-18) introduced the ``ci-aggregator`` workflow
(``.github/workflows/ci-aggregator.yml`` + ``scripts/ci/ci_aggregator.py``,
Tomas Tag-37 PR #244 ``e29439dc``) as the single Required-Status-Check
on ``main``. The aggregator is in a ~1-week observation window: it
runs in parallel with the six legacy Required-Status-Check names
(``License-Hygiene Gate``, ``wirelang suite production / shadow``,
``production-vs-sandbox drift envelope``, ``cross-repo drift``,
``Phase-2 Aggregator``). After ~1 week of clean observation, the
Mira-Hand-cutover (ADR-0068 §Migration-Step-3) drops the six legacy
names and leaves ``ci-aggregator`` as the sole Required-Status-Check.

During that window we need three things that the aggregator workflow
itself does NOT produce:

  1. **Per-sub-workflow failure-rate over a sliding window** (50 / 100
     / 500 runs). Operator question: "is sub-workflow X regressing or
     stable over the last 50 aggregator runs?"
  2. **Decision-latency p50/p95/p99** per sub-workflow wait-loop.
     Operator question: "is the aggregator wasting wall-clock waiting
     for sub-workflow X to complete?"
  3. **Drift-detection between aggregator-verdict and the union of the
     six legacy Required-Status verdicts.** Operator question: "would
     the aggregator have blocked anything that the six legacy checks
     let through, or vice versa?" If this drift fires, the cutover
     window must be extended.

This tracker is read-only: it polls ``gh api`` for the latest N
aggregator runs and writes the rollups to two formats, **JSON** (for
operator/CI consumption) and **Prometheus textfile** (for scrape by
the persona-engine Prometheus node-exporter at the standard
``/var/lib/prometheus/node-exporter/`` path).

Sandbox boundary
----------------

When invoked without ``GITHUB_TOKEN`` and with
``WAKIR_AGGREGATOR_TRACKER_DRY_RUN=1`` set, the script reads a fixture
JSON from ``--fixture-runs`` instead of hitting the GitHub API. This
mirrors the ``ci_aggregator.py`` decide-only / live split and is the
mode used by the hermetic test suite
(``tests/observability/test_aggregator_failure_rate_tracker.py``).

Pure-function-vs-IO split
-------------------------

Everything above the ``# --- I/O boundary ---`` marker is pure-function,
hermetic-test target. The I/O wrappers (``fetch_aggregator_runs``,
``fetch_run_jobs``) are isolated at the bottom.

Anchors
-------

* ADR-0068 §Beschluss (approved 2026-05-18, AR ~12:55 CEST) — parent
  ADR that this tracker observes.
* ADR-0068 §Migration-Strategy-Step-2 — the "verify on 2-3 follow-up
  PRs that ci-aggregator verdict matches the union of the six legacy
  verdicts" check that ``compute_legacy_vs_aggregator_drift`` answers.
* ``feedback_branch_protection_check_names.md`` (memory) — Required-
  vs-display-name footgun that the aggregator structurally fixed and
  that this tracker is the observability-side of.

Author: Noa Bergstroem (SRE)
Tag: 38 (KW-22)

Tag-42 patch (2026-05-18)
-------------------------

``fetch_aggregator_runs_via_gh_cli`` had a 404-bug on Reza's Tag-41
probe-run. Query parameters (``per_page``, ``page``) were passed via
``gh api -f key=value``, which adds the field to the request body and
forces ``gh`` to use POST semantics. The GitHub-Actions ``runs``
endpoint only accepts GET; the result was HTTP 404 from the API and
``subprocess.CalledProcessError`` for the operator. The fix
(`_build_gh_cli_get_cmd`) embeds query params in the URL path and
sets ``-X GET`` explicitly, matching the documented gh-cli pattern
for paginated GET endpoints. Hermetic test
``test_build_gh_cli_get_cmd_embeds_query_in_path`` enforces the
invariant so a regression cannot land silently.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
#
# Sliding-window sizes the tracker reports on. 50 is the operator's
# "last shift" view, 100 is the "last day at 20 PRs/day" view, 500 is
# the "rolling weekly" view. Three windows = three columns in the
# rollup JSON / three series in Prometheus.
#
# Drift-detection threshold: zero. A single divergence between the
# aggregator-verdict and the union of the six legacy verdicts on the
# same head-SHA is a Mira-Notify event. ADR-0068 §Migration-Step-2
# expects a clean observation window before cutover.

WINDOW_SIZES: Tuple[int, ...] = (50, 100, 500)
DEFAULT_PROMETHEUS_TEXTFILE_PATH = (
    "/var/lib/prometheus/node-exporter/wakir_aggregator_failure_rate.prom"
)

# The six legacy Required-Status-Check display names that the
# aggregator union-checks against. Source: ADR-0068 §Beschluss + the
# ``SUB_WORKFLOWS`` inventory in ``scripts/ci/ci_aggregator.py``.
# Keep this list in lock-step with that inventory; the hermetic test
# ``test_legacy_required_names_match_aggregator_inventory`` enforces it.

LEGACY_REQUIRED_NAMES: Tuple[str, ...] = (
    "License-Hygiene Gate (ADR-0061)",
    "wirelang suite with rfc8785 + jsonschema",
    "wirelang suite without rfc8785 / jsonschema (shadow)",
    "production-vs-sandbox drift envelope",
    "cross-repo drift (wakir-runtime ↔ wakir-protocol)",
    "Phase-2 Aggregator (All Gates + Cross-Gate Non-Interference)",
)

AGGREGATOR_CHECK_NAME = "ci-aggregator"
AGGREGATOR_WORKFLOW_FILE = "ci-aggregator.yml"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class JobOutcome:
    """One per-job verdict on one aggregator run.

    Mirrors the ``actions/runs/{id}/jobs`` API shape but trims to the
    fields the tracker actually reads. ``duration_seconds`` is computed
    from ``started_at`` and ``completed_at`` at fetch time and is the
    field the latency rollup consumes.
    """

    name: str
    conclusion: str  # success / failure / cancelled / timed_out / skipped
    duration_seconds: float
    started_at: str
    completed_at: str


@dataclass(frozen=True)
class AggregatorRun:
    """One ``ci-aggregator`` workflow run + its per-job outcomes.

    ``head_sha`` is the SHA the aggregator polled against. ``jobs``
    holds the per-sub-workflow outcomes (one entry per inventory row,
    plus the aggregator's own ``ci-aggregator`` job).
    """

    run_id: int
    head_sha: str
    conclusion: str  # aggregator's own conclusion
    created_at: str
    jobs: Tuple[JobOutcome, ...]


@dataclass
class FailureRateRollup:
    """Per-sub-workflow failure-rate rollup across sliding windows."""

    check_name: str
    by_window: Dict[int, "WindowRollup"] = field(default_factory=dict)


@dataclass
class WindowRollup:
    """Failure-rate + latency over one sliding window."""

    window_size: int
    sample_count: int
    failure_count: int
    success_count: int
    skipped_count: int
    latency_p50_seconds: float
    latency_p95_seconds: float
    latency_p99_seconds: float

    @property
    def failure_rate(self) -> float:
        """Failures / (failures + successes). Skipped excluded.

        Skipped runs are not "the sub-workflow ran and decided no" —
        they are "the sub-workflow did not run at all" (path-filter
        skip-ok). Including them in the denominator would
        artificially deflate the failure-rate when path-filters are
        narrow. The operator question is "when this sub-workflow DID
        run, how often did it fail", not "what share of all PRs hit
        a failure".
        """
        ran = self.failure_count + self.success_count
        if ran == 0:
            return 0.0
        return self.failure_count / ran


@dataclass(frozen=True)
class DriftEvent:
    """One divergence between aggregator-verdict and legacy-union verdict.

    ``aggregator_verdict`` and ``legacy_union_verdict`` are both one of
    ``success``, ``failure``, ``mixed``, ``missing``. ``mixed`` means
    "at least one legacy check failed and at least one succeeded on
    the same head SHA" — the union is then ``failure`` but the
    operator's mental model wants to know whether ``ci-aggregator`` is
    the one disagreeing or just one of the legacy checks.
    """

    run_id: int
    head_sha: str
    aggregator_verdict: str
    legacy_union_verdict: str
    legacy_per_check: Mapping[str, str]


# ---------------------------------------------------------------------------
# Pure-function rollups (hermetic test target)
# ---------------------------------------------------------------------------


def _percentile(values: Sequence[float], pct: float) -> float:
    """Linear-interpolation percentile.

    Pure function, no numpy dependency. Empty sequence returns 0.0
    (the rollup field is "no samples = no latency", not "infinity").
    """
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    s = sorted(values)
    # Nearest-rank with linear interpolation between adjacent ranks.
    k = (len(s) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    frac = k - lo
    return s[lo] * (1.0 - frac) + s[hi] * frac


def _window_slice(
    runs: Sequence[AggregatorRun], window_size: int
) -> Sequence[AggregatorRun]:
    """Return the most-recent ``window_size`` runs.

    Runs are assumed to be ordered most-recent first (the order the
    ``actions/runs`` API returns). Window smaller than the available
    samples is honoured; window larger returns everything.
    """
    return runs[:window_size]


def rollup_failure_rate(
    runs: Sequence[AggregatorRun],
    check_names: Sequence[str],
    window_sizes: Sequence[int] = WINDOW_SIZES,
) -> List[FailureRateRollup]:
    """Compute per-check failure-rate + latency rollups.

    Pure function: no I/O. The hermetic test
    ``test_rollup_failure_rate_*`` feeds this with synthetic
    ``AggregatorRun`` lists and asserts the output shape.

    Args:
        runs: most-recent-first ordered list of aggregator runs.
        check_names: the set of check_name strings to roll up (the
            six legacy + the aggregator's own).
        window_sizes: sliding window sizes. Default ``WINDOW_SIZES``.

    Returns:
        One ``FailureRateRollup`` per check_name, with one
        ``WindowRollup`` per window_size.
    """
    out: List[FailureRateRollup] = []
    for check in check_names:
        rollup = FailureRateRollup(check_name=check)
        for win in window_sizes:
            slice_runs = _window_slice(runs, win)
            failures = 0
            successes = 0
            skipped = 0
            durations: List[float] = []
            for run in slice_runs:
                for job in run.jobs:
                    if job.name != check:
                        continue
                    if job.conclusion == "success":
                        successes += 1
                    elif job.conclusion == "skipped":
                        skipped += 1
                    elif job.conclusion in ("failure", "cancelled", "timed_out"):
                        failures += 1
                    # Other conclusions (neutral, action_required) are
                    # rare; we lump them into "neither succ nor fail".
                    if job.duration_seconds > 0:
                        durations.append(job.duration_seconds)
            rollup.by_window[win] = WindowRollup(
                window_size=win,
                sample_count=successes + failures + skipped,
                failure_count=failures,
                success_count=successes,
                skipped_count=skipped,
                latency_p50_seconds=_percentile(durations, 50),
                latency_p95_seconds=_percentile(durations, 95),
                latency_p99_seconds=_percentile(durations, 99),
            )
        out.append(rollup)
    return out


def compute_legacy_vs_aggregator_drift(
    runs: Sequence[AggregatorRun],
    legacy_required_names: Sequence[str] = LEGACY_REQUIRED_NAMES,
    aggregator_check_name: str = AGGREGATOR_CHECK_NAME,
) -> List[DriftEvent]:
    """Detect divergence between aggregator verdict and legacy-union.

    Pure function. For each run, compute the union-verdict of the six
    legacy required checks and compare to the aggregator's own job
    conclusion. Yield one ``DriftEvent`` for every divergence.

    Union semantics:
      - all six legacy checks ``success`` => union ``success``
      - any legacy check ``failure|cancelled|timed_out`` => union
        ``failure``
      - all six legacy checks ``skipped`` => union ``success`` (no
        path-filter triggered, nothing to fail). This is the "skip-ok"
        equivalent; the aggregator emits ``success`` here too.
      - any legacy check missing entirely from the run's jobs list =>
        union ``missing`` (the path-filter pattern that ADR-0068
        structurally eliminates).
      - mixed success+skipped => union ``success`` (skip-ok rolls in).

    A drift event fires if and only if union != aggregator-conclusion.

    Args:
        runs: aggregator runs in any order; drift is per-run, ordering
            does not matter.
        legacy_required_names: the six legacy names from
            ADR-0068 / Aggregator inventory.
        aggregator_check_name: the aggregator's own job display name
            (``ci-aggregator``).

    Returns:
        List of ``DriftEvent``, one per divergent run. Empty list when
        the cutover window is clean.
    """
    events: List[DriftEvent] = []
    legacy_set = set(legacy_required_names)
    for run in runs:
        per_check: Dict[str, str] = {}
        agg_concl: Optional[str] = None
        for job in run.jobs:
            if job.name == aggregator_check_name:
                agg_concl = job.conclusion
            elif job.name in legacy_set:
                per_check[job.name] = job.conclusion
        # Compute legacy-union.
        union = _legacy_union(per_check, legacy_required_names)
        if agg_concl is None:
            # The aggregator job itself did not run on this SHA.
            # Surface as drift only if the legacy set has a verdict;
            # otherwise the SHA pre-dates aggregator existence and is
            # not interesting.
            if union not in ("missing",):
                events.append(
                    DriftEvent(
                        run_id=run.run_id,
                        head_sha=run.head_sha,
                        aggregator_verdict="missing",
                        legacy_union_verdict=union,
                        legacy_per_check=dict(per_check),
                    )
                )
            continue
        # Normalise aggregator-conclusion: the aggregator emits
        # ``success`` / ``failure`` / ``cancelled`` / ``timed_out`` at
        # the job level. Treat the latter three as ``failure`` for
        # drift purposes.
        agg_norm = "success" if agg_concl == "success" else "failure"
        if union != agg_norm:
            events.append(
                DriftEvent(
                    run_id=run.run_id,
                    head_sha=run.head_sha,
                    aggregator_verdict=agg_norm,
                    legacy_union_verdict=union,
                    legacy_per_check=dict(per_check),
                )
            )
    return events


def _legacy_union(
    per_check: Mapping[str, str], legacy_names: Sequence[str]
) -> str:
    """Reduce per-check legacy verdicts to a union verdict.

    Pure helper for ``compute_legacy_vs_aggregator_drift``. Hoisted to
    module level for direct hermetic-test coverage.
    """
    if not per_check:
        return "missing"
    any_present = False
    any_failure = False
    any_success = False
    for name in legacy_names:
        c = per_check.get(name)
        if c is None:
            continue
        any_present = True
        if c in ("failure", "cancelled", "timed_out"):
            any_failure = True
        elif c == "success":
            any_success = True
        # ``skipped`` counts as "no path-filter triggered" → skip-ok.
    if not any_present:
        return "missing"
    if any_failure:
        return "failure"
    # any_success or all-skipped both roll up to ``success`` (skip-ok
    # is the aggregator's success equivalent).
    return "success"


def render_prometheus_textfile(
    rollups: Sequence[FailureRateRollup],
    drift_events: Sequence[DriftEvent],
    *,
    timestamp_unixtime: Optional[float] = None,
) -> str:
    """Render rollups + drift events as Prometheus textfile format.

    Pure function. Output schema:

      # HELP wakir_aggregator_failure_rate Per-sub-workflow failure-rate
      # TYPE wakir_aggregator_failure_rate gauge
      wakir_aggregator_failure_rate{check="...",window="50"} 0.04
      ...
      # HELP wakir_aggregator_latency_seconds p50/p95/p99 per sub-workflow
      # TYPE wakir_aggregator_latency_seconds gauge
      wakir_aggregator_latency_seconds{check="...",window="50",pct="p50"} 12.3
      ...
      # HELP wakir_aggregator_drift_events Drift event count
      # TYPE wakir_aggregator_drift_events gauge
      wakir_aggregator_drift_events 0

    Label-escaping: check names contain spaces and parens; the textfile
    format escapes via standard quoted-label-value semantics. We use
    a simple sanitiser: backslash-escape ``"`` and ``\\``, then quote.
    """
    if timestamp_unixtime is None:
        timestamp_unixtime = time.time()
    ts_ms = int(timestamp_unixtime * 1000)
    lines: List[str] = []
    lines.append(
        "# HELP wakir_aggregator_failure_rate Per-sub-workflow failure-rate "
        "(failures / (failures + successes)) over a sliding window of "
        "ci-aggregator runs. ADR-0068 §Migration-Step-2 observability."
    )
    lines.append("# TYPE wakir_aggregator_failure_rate gauge")
    for r in rollups:
        for win, wr in sorted(r.by_window.items()):
            check_esc = _escape_label(r.check_name)
            lines.append(
                f'wakir_aggregator_failure_rate{{check="{check_esc}",'
                f'window="{win}"}} {wr.failure_rate:.6f} {ts_ms}'
            )
    lines.append("")
    lines.append(
        "# HELP wakir_aggregator_latency_seconds Per-sub-workflow "
        "wait-loop latency percentiles (p50/p95/p99) in seconds."
    )
    lines.append("# TYPE wakir_aggregator_latency_seconds gauge")
    for r in rollups:
        for win, wr in sorted(r.by_window.items()):
            check_esc = _escape_label(r.check_name)
            for pct_label, pct_value in (
                ("p50", wr.latency_p50_seconds),
                ("p95", wr.latency_p95_seconds),
                ("p99", wr.latency_p99_seconds),
            ):
                lines.append(
                    f'wakir_aggregator_latency_seconds{{check="{check_esc}",'
                    f'window="{win}",pct="{pct_label}"}} {pct_value:.3f} {ts_ms}'
                )
    lines.append("")
    lines.append(
        "# HELP wakir_aggregator_sample_count Number of samples per "
        "sliding window per sub-workflow."
    )
    lines.append("# TYPE wakir_aggregator_sample_count gauge")
    for r in rollups:
        for win, wr in sorted(r.by_window.items()):
            check_esc = _escape_label(r.check_name)
            lines.append(
                f'wakir_aggregator_sample_count{{check="{check_esc}",'
                f'window="{win}"}} {wr.sample_count} {ts_ms}'
            )
    lines.append("")
    lines.append(
        "# HELP wakir_aggregator_drift_events Number of ci-aggregator "
        "runs where aggregator-verdict diverged from the union of the "
        "six legacy Required-Status-Check verdicts. ADR-0068 cutover "
        "window observability. A non-zero value blocks Mira-Hand "
        "cutover (ADR-0068 §Migration-Step-3) until investigated."
    )
    lines.append("# TYPE wakir_aggregator_drift_events gauge")
    lines.append(f"wakir_aggregator_drift_events {len(drift_events)} {ts_ms}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _escape_label(s: str) -> str:
    """Prometheus-textfile-format label-value escape.

    Backslash-escape ``\\`` and ``"``; that is the full quoted-label-
    value escape set per the Prometheus exposition format spec.
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


def render_json_rollup(
    rollups: Sequence[FailureRateRollup],
    drift_events: Sequence[DriftEvent],
    *,
    timestamp_unixtime: Optional[float] = None,
) -> str:
    """Render rollups + drift events as operator-readable JSON.

    Pure function. Output schema mirrors the textfile structure but
    nests per-check / per-window for human navigability:

      {
        "timestamp": "...",
        "rollups": [
          {
            "check_name": "...",
            "windows": {
              "50": {"failure_rate": 0.0, "samples": 0, ...},
              ...
            }
          }
        ],
        "drift_events": [...]
      }
    """
    if timestamp_unixtime is None:
        timestamp_unixtime = time.time()
    out = {
        "schema_version": 1,
        "anchor": "ADR-0068 §Migration-Step-2",
        "timestamp_unixtime": timestamp_unixtime,
        "rollups": [],
        "drift_events": [],
        "summary": {
            "rollup_count": len(rollups),
            "drift_event_count": len(drift_events),
        },
    }
    for r in rollups:
        windows: Dict[str, dict] = {}
        for win, wr in sorted(r.by_window.items()):
            windows[str(win)] = {
                "window_size": wr.window_size,
                "sample_count": wr.sample_count,
                "failure_count": wr.failure_count,
                "success_count": wr.success_count,
                "skipped_count": wr.skipped_count,
                "failure_rate": wr.failure_rate,
                "latency_p50_seconds": wr.latency_p50_seconds,
                "latency_p95_seconds": wr.latency_p95_seconds,
                "latency_p99_seconds": wr.latency_p99_seconds,
            }
        out["rollups"].append(
            {"check_name": r.check_name, "windows": windows}
        )
    for ev in drift_events:
        out["drift_events"].append(
            {
                "run_id": ev.run_id,
                "head_sha": ev.head_sha,
                "aggregator_verdict": ev.aggregator_verdict,
                "legacy_union_verdict": ev.legacy_union_verdict,
                "legacy_per_check": dict(ev.legacy_per_check),
            }
        )
    return json.dumps(out, indent=2, sort_keys=True) + "\n"


def parse_run_payload(payload: dict, jobs_payload: dict) -> AggregatorRun:
    """Parse one ``actions/runs/{id}`` + its jobs into an AggregatorRun.

    Pure function. ``payload`` is the workflow-run JSON; ``jobs_payload``
    is the ``actions/runs/{id}/jobs`` JSON. The two are merged into
    one ``AggregatorRun`` instance ready for rollup.

    Tolerates missing fields (older API versions, GitHub edge cases):
    missing ``started_at`` / ``completed_at`` => duration 0.0.
    """
    jobs_raw = jobs_payload.get("jobs") or []
    jobs: List[JobOutcome] = []
    for j in jobs_raw:
        duration = _compute_duration_seconds(
            j.get("started_at"), j.get("completed_at")
        )
        jobs.append(
            JobOutcome(
                name=j.get("name") or "",
                conclusion=j.get("conclusion") or "",
                duration_seconds=duration,
                started_at=j.get("started_at") or "",
                completed_at=j.get("completed_at") or "",
            )
        )
    return AggregatorRun(
        run_id=int(payload.get("id") or 0),
        head_sha=payload.get("head_sha") or "",
        conclusion=payload.get("conclusion") or "",
        created_at=payload.get("created_at") or "",
        jobs=tuple(jobs),
    )


def _compute_duration_seconds(started_at: Optional[str], completed_at: Optional[str]) -> float:
    """Compute job duration in seconds from ISO-8601 timestamps.

    Pure helper. Returns 0.0 on missing or unparseable inputs. The
    GitHub-Actions API uses ``YYYY-MM-DDTHH:MM:SSZ`` (UTC).
    """
    if not started_at or not completed_at:
        return 0.0
    try:
        # stdlib-only parse; tolerate trailing ``Z`` by stripping it.
        from datetime import datetime, timezone

        def _parse(ts: str) -> "datetime":
            ts2 = ts.replace("Z", "+00:00")
            return datetime.fromisoformat(ts2)

        delta = _parse(completed_at) - _parse(started_at)
        return max(0.0, delta.total_seconds())
    except (ValueError, TypeError):
        return 0.0


# ---------------------------------------------------------------------------
# I/O boundary
# ---------------------------------------------------------------------------
# Everything below this marker calls ``gh api`` or ``urllib``. Not
# hermetically unit-tested; integration coverage comes from the
# dry-run-fixture-mode the entrypoint supports.
# ---------------------------------------------------------------------------


def _gh_api_get(
    path: str,
    *,
    token: str,
    query: Optional[dict] = None,
    timeout_seconds: float = 30.0,
) -> dict:
    """Minimal GitHub-API GET over urllib. Mirrors ci_aggregator._gh_api."""
    url = f"https://api.github.com{path}"
    if query:
        url = f"{url}?{urllib.parse.urlencode(query)}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header(
        "User-Agent", "wakir-aggregator-failure-rate-tracker/1.0 (Tag-38)"
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_aggregator_runs(
    *,
    owner: str,
    repo: str,
    token: str,
    max_runs: int = 500,
    workflow_file: str = AGGREGATOR_WORKFLOW_FILE,
) -> List[AggregatorRun]:
    """Fetch the most-recent N aggregator runs + their per-job outcomes.

    Pages via the ``per_page=100`` cap. Returns at most ``max_runs``
    entries, most-recent-first.

    For each run, also fetches the ``actions/runs/{id}/jobs`` payload
    so per-sub-workflow conclusions are populated. This is N+1
    requests; for max_runs=500 that is up to 505 API calls. GitHub
    REST rate-limit for an authenticated token is 5000 req/hour, well
    above this ceiling.
    """
    out: List[AggregatorRun] = []
    pages_needed = (max_runs + 99) // 100
    for page in range(1, pages_needed + 1):
        runs_payload = _gh_api_get(
            f"/repos/{owner}/{repo}/actions/workflows/"
            f"{urllib.parse.quote(workflow_file)}/runs",
            token=token,
            query={"per_page": 100, "page": page},
        )
        runs = runs_payload.get("workflow_runs") or []
        if not runs:
            break
        for r in runs:
            if len(out) >= max_runs:
                return out
            jobs_payload = _gh_api_get(
                f"/repos/{owner}/{repo}/actions/runs/{r['id']}/jobs",
                token=token,
                query={"per_page": 100},
            )
            out.append(parse_run_payload(r, jobs_payload))
        if len(runs) < 100:
            break
    return out


def _build_gh_cli_get_cmd(path: str, query: Optional[dict] = None) -> List[str]:
    """Build a ``gh api`` command-line for a GET with query params.

    Tag-42 fix for the Reza-probe-run 404. The previous implementation
    used ``-f key=value`` for ``per_page`` and ``page``. With ``gh api``,
    ``-f`` adds the field to the request *body* (and forces the method
    to POST), which for a GET endpoint either yields HTTP 404 (path
    + method mismatch) or silently drops the param. The two correct
    options are:

      1. Embed the query in the path: ``gh api '/repos/.../runs?per_page=100&page=1'``
      2. Use ``-X GET`` together with ``-F`` (raw, typed).

    We pick option 1: it is the form documented in the ``gh-cli``
    manual for paginated GET endpoints, it is robust against future
    ``gh`` versions changing ``-f`` semantics, and it keeps the URL
    identical between the urllib (``_gh_api_get``) and gh-cli paths so
    the two modes are byte-equivalent for the same input.

    Pure-function helper. Hermetic test
    ``test_build_gh_cli_get_cmd_embeds_query_in_path`` enforces the
    invariant.
    """
    if query:
        # Sort for deterministic test assertions; GitHub does not care
        # about query-param order.
        encoded = urllib.parse.urlencode(sorted(query.items()))
        full_path = f"{path}?{encoded}"
    else:
        full_path = path
    return ["gh", "api", "-X", "GET", full_path]


def fetch_aggregator_runs_via_gh_cli(
    *,
    owner: str,
    repo: str,
    max_runs: int = 500,
    workflow_file: str = AGGREGATOR_WORKFLOW_FILE,
) -> List[AggregatorRun]:
    """Fetch via the ``gh`` CLI instead of raw urllib.

    Useful when the operator is on a workstation with ``gh auth login``
    already configured but no ``GITHUB_TOKEN`` env var set. Delegates
    to ``gh api`` with the same paths.

    Tag-42 fix: query parameters (``per_page``, ``page``) are now embedded
    in the URL path rather than passed as ``-f key=value`` form fields.
    The latter caused ``gh`` to POST the body and the API to return 404
    on Reza's Tag-41 probe-run. See ``_build_gh_cli_get_cmd``.
    """
    out: List[AggregatorRun] = []
    pages_needed = (max_runs + 99) // 100
    for page in range(1, pages_needed + 1):
        runs_path = (
            f"/repos/{owner}/{repo}/actions/workflows/"
            f"{urllib.parse.quote(workflow_file)}/runs"
        )
        cmd = _build_gh_cli_get_cmd(
            runs_path, query={"per_page": 100, "page": page}
        )
        proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
        runs_payload = json.loads(proc.stdout)
        runs = runs_payload.get("workflow_runs") or []
        if not runs:
            break
        for r in runs:
            if len(out) >= max_runs:
                return out
            jobs_path = f"/repos/{owner}/{repo}/actions/runs/{r['id']}/jobs"
            jobs_cmd = _build_gh_cli_get_cmd(
                jobs_path, query={"per_page": 100}
            )
            jobs_proc = subprocess.run(
                jobs_cmd, check=True, capture_output=True, text=True
            )
            jobs_payload = json.loads(jobs_proc.stdout)
            out.append(parse_run_payload(r, jobs_payload))
        if len(runs) < 100:
            break
    return out


def load_fixture_runs(fixture_path: Path) -> List[AggregatorRun]:
    """Load AggregatorRun list from a fixture JSON file.

    Fixture schema: a JSON list of objects matching ``payload`` +
    ``jobs_payload`` from ``parse_run_payload``::

        [
          {
            "payload": {"id": 1, "head_sha": "...", "conclusion": "...",
                        "created_at": "..."},
            "jobs_payload": {"jobs": [{"name": "...", "conclusion": "...",
                                       "started_at": "...",
                                       "completed_at": "..."}]}
          },
          ...
        ]

    Used by the hermetic-test entrypoint and dry-run operator mode.
    """
    raw = json.loads(fixture_path.read_text(encoding="utf-8"))
    out: List[AggregatorRun] = []
    for entry in raw:
        out.append(
            parse_run_payload(
                entry.get("payload") or {}, entry.get("jobs_payload") or {}
            )
        )
    return out


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="aggregator-failure-rate-tracker",
        description=(
            "Aggregator-Failure-Rate-Tracker (ADR-0068 Tag-38 SRE). "
            "Polls ci-aggregator runs, rolls up per-sub-workflow "
            "failure-rate + latency, detects drift between aggregator "
            "verdict and the six legacy Required-Status-Check verdicts."
        ),
    )
    parser.add_argument(
        "--owner",
        type=str,
        default=os.environ.get("GITHUB_REPOSITORY_OWNER", "wakir-labs"),
        help="GitHub repo owner (default: env GITHUB_REPOSITORY_OWNER or 'wakir-labs').",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=(os.environ.get("GITHUB_REPOSITORY") or "wakir-labs/wakir-runtime").split("/")[-1],
        help="GitHub repo name (default: env GITHUB_REPOSITORY tail or 'wakir-runtime').",
    )
    parser.add_argument(
        "--max-runs",
        type=int,
        default=500,
        help="Max aggregator runs to poll. Default 500 (matches largest sliding-window).",
    )
    parser.add_argument(
        "--mode",
        choices=("live", "gh-cli", "fixture"),
        default="gh-cli",
        help=(
            "``live``: urllib + GITHUB_TOKEN. ``gh-cli``: gh api (default, "
            "operator-friendly). ``fixture``: read --fixture-runs (hermetic-test)."
        ),
    )
    parser.add_argument(
        "--fixture-runs",
        type=Path,
        default=None,
        help="Path to fixture JSON (mode=fixture only).",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=None,
        help="Write JSON rollup to this path. If omitted, writes to stdout.",
    )
    parser.add_argument(
        "--prometheus-output",
        type=Path,
        default=None,
        help=(
            "Write Prometheus textfile to this path. If omitted, "
            "skip Prometheus emit. Conventional value: "
            f"{DEFAULT_PROMETHEUS_TEXTFILE_PATH}"
        ),
    )
    parser.add_argument(
        "--check-names",
        type=str,
        default=None,
        help=(
            "Comma-separated check_name list to roll up. Default: the "
            "six legacy required names + 'ci-aggregator'."
        ),
    )
    args = parser.parse_args(argv)

    # Determine check_names.
    if args.check_names:
        check_names: List[str] = [
            n.strip() for n in args.check_names.split(",") if n.strip()
        ]
    else:
        check_names = list(LEGACY_REQUIRED_NAMES) + [AGGREGATOR_CHECK_NAME]

    # Fetch runs.
    if args.mode == "fixture":
        if not args.fixture_runs:
            print(
                "ERROR: --fixture-runs required in mode=fixture.",
                file=sys.stderr,
            )
            return 2
        runs = load_fixture_runs(args.fixture_runs)
    elif args.mode == "gh-cli":
        runs = fetch_aggregator_runs_via_gh_cli(
            owner=args.owner, repo=args.repo, max_runs=args.max_runs
        )
    else:  # live
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            print(
                "ERROR: GITHUB_TOKEN unset; cannot run mode=live.",
                file=sys.stderr,
            )
            return 2
        runs = fetch_aggregator_runs(
            owner=args.owner,
            repo=args.repo,
            token=token,
            max_runs=args.max_runs,
        )

    print(
        f"Fetched {len(runs)} aggregator runs (mode={args.mode}).",
        file=sys.stderr,
    )

    # Rollups.
    rollups = rollup_failure_rate(runs, check_names)
    drift_events = compute_legacy_vs_aggregator_drift(runs)

    # Emit.
    ts = time.time()
    json_text = render_json_rollup(rollups, drift_events, timestamp_unixtime=ts)
    if args.json_output:
        args.json_output.write_text(json_text, encoding="utf-8")
        print(f"Wrote JSON rollup to {args.json_output}", file=sys.stderr)
    else:
        sys.stdout.write(json_text)

    if args.prometheus_output:
        prom_text = render_prometheus_textfile(
            rollups, drift_events, timestamp_unixtime=ts
        )
        args.prometheus_output.write_text(prom_text, encoding="utf-8")
        print(
            f"Wrote Prometheus textfile to {args.prometheus_output}",
            file=sys.stderr,
        )

    # Exit code: 0 if no drift, 1 if drift events present.
    # Operator semantics: a non-zero exit blocks the Mira-Hand-cutover
    # script (ADR-0068 §Migration-Step-3) from running.
    if drift_events:
        print(
            f"DRIFT DETECTED: {len(drift_events)} aggregator runs "
            f"disagreed with legacy-union verdict. Mira-Notify required.",
            file=sys.stderr,
        )
        return 1
    print(
        "No drift detected. Aggregator verdict matches legacy-union on "
        "all sampled runs. Cutover window remains clean.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
