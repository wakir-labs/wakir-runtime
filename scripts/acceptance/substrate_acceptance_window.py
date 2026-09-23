#!/usr/bin/env python3
# SPDX-License-Identifier: BUSL-1.1
# SPDX-FileCopyrightText: 2026 Callandor GmbH and contributors
"""The judge for the ADR-0076 seven-day acceptance window.

The other half of ``scripts/acceptance/substrate-acceptance-probe.sh``.
The probe samples on the node and never judges; this file judges and
never samples. It is the piece that turns a series of measurements into
the three assurances and the two falsifications of ADR-0076.

Why the judgement lives here and not in the probe
-------------------------------------------------

ADR-0076's acceptance turns on one distinction: *running* versus *still
running out of the cache*. That distinction is not present in any single
state -- at the moment of a single sample the two are identical, which is
precisely why *Smoke 6/6* on 2026-05-15 was both correct and worthless.
It is present only in the movement between samples. A verdict therefore
cannot be computed where the samples are taken; it can only be computed
where the series is.

Two rules, and they are the whole design
----------------------------------------

**1. The absence of a measurement is not a passed measurement.**
Every assurance can end in three states, never two. ``require_measured``
below is the single place where a missing value becomes ``UNKNOWN``; a
value that is present and wrong becomes ``FAIL`` at a ``violations``
append. Those are the two lines to look at when asking how this file
tells "not measured" from "measured and bad". ``UNKNOWN`` exits 2 and is
not a pass.

**2. The verdict is computed, never read.**
The sample record carries measurements and no opinion. If a record ever
grows a verdict-shaped field, this reader refuses the whole run
(``sample_carries_a_verdict``) rather than get into the habit of
believing the thing it observes. PR #560 and its own Zone-M review found
that defect twice in one day, in two different shapes; this is the
structural answer rather than a third comment about it.

Which samples are judged
------------------------

Two kinds of episode are *deliberate* breakage and are cut out of the
standing assurances:

* the cold-agent counter-probe (F2), between ``cold-agent-stop`` and
  ``cold-agent-start``. ADR-0076 Auflage 2 keeps it in the window even
  though it turns the substrate red; folding it into Z1..Z4 would mean
  the window can only pass if the mandated falsification is skipped.
* the mandatory negative control, between ``negative-control-start`` and
  ``negative-control-end``.

Both are judged, separately and on their own terms. An episode that was
opened and never closed makes the window ``UNKNOWN``: an open exclusion
that silently swallows the rest of the series is the way this mechanism
would fail dishonestly, so it is made to fail loudly instead.

Exit codes
----------

    0  PASS     -- every assurance and both falsifications hold, over a
                   window with sufficient coverage, and the negative
                   control was performed and came out red
    1  FAIL     -- something was measured and is bad
    2  UNKNOWN  -- something was not measured, or the reader could not
                   read its own inputs

The consuming lane must treat 1 and 2 alike: neither is evidence. The
distinction is for the person reading the report.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_EXPECTED = "wakir-runtime/substrate-acceptance-sample@1"

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

#: Field names that must never appear in a sample. The probe does not
#: write them; a record that carries one was written by something else,
#: or by a probe that has started forming opinions. Either way the run
#: is not read.
FORBIDDEN_SAMPLE_KEYS = frozenset(
    {
        "verdict",
        "status",
        "ok",
        "healthy",
        "pass",
        "z1",
        "z2",
        "z3",
        "z4",
        "f1",
        "f2",
        "result",
    }
)

#: Source-status vocabulary. Closed on purpose: a status string this
#: reader does not know yields UNKNOWN, never PASS and never FAIL.
#: A probe that grows a new status has to be read by a reader that
#: knows what it means.
STATUS_OK = "ok"
STATUS_UNMEASURED = "unmeasured"
TARGET_BAD_PREFIX = "target_bad_"

DEFAULT_WINDOW_SECONDS = 7 * 24 * 3600
DEFAULT_SVID_TTL_SECONDS = 3600
DEFAULT_PROBE_INTERVAL_SECONDS = 3600
#: ``ca_ttl`` stays at 24 h by ADR-0076; the cold-agent probe has to
#: outlast the CA overlap to mean anything.
DEFAULT_CA_OVERLAP_SECONDS = 24 * 3600
DEFAULT_MIN_ROTATIONS = 6
#: ``ca_ttl`` stays at 24 h by ADR-0076, so the signing intermediate is
#: expected to turn over once a day.
DEFAULT_ROTATION_PERIOD_SECONDS = 24 * 3600
#: The re-staging timer runs well under ``ca_ttl``; ADR-0076 proposes
#: 30 min. Two hours is four missed runs, not a blip.
DEFAULT_ANCHOR_RESTAGE_MAX_SECONDS = 2 * 3600
#: The agent rewrites ``agent-data.json`` when its own credentials turn
#: over; SPIRE documents no cadence for it. Six hours is the same floor
#: the substrate-liveness probe uses for state staleness.
DEFAULT_Z3_MIN_SPAN_SECONDS = 6 * 3600
#: The test plan asks for the anchor to stay removed for at least two
#: sampling intervals. Two samples actually seeing it gone is the same
#: statement, measured rather than intended.
DEFAULT_NEGATIVE_CONTROL_MIN_ABSENT = 2


class Unmeasured(Exception):
    """A value this judgement needs was not measured.

    Raised only by :func:`require_measured` and by the status readers,
    and always caught into an ``UNKNOWN``. It is never converted into a
    ``FAIL``: "nobody looked" and "somebody looked and it was bad" are
    different statements about a substrate and the whole point of this
    file is that they stay different.
    """


class Unreadable(Exception):
    """The judge could not read its own inputs. Exits 2, never 0."""


def require_measured(field_name: str, value, at: str | None = None):
    """The one line where an absent measurement becomes UNKNOWN.

    Every assurance in this file funnels its inputs through here. There
    is no second path by which a ``None`` can reach a comparison, and
    therefore no path by which "not measured" can come out as "fine".
    """
    if value is None:
        where = f" in the sample at {at}" if at else ""
        raise Unmeasured(f"{field_name} was not measured{where}")
    return value


@dataclass(frozen=True)
class Sample:
    """One probe record. Measurements only; no verdict."""

    observed_at_epoch: int
    observed_at: str
    side: str
    marker: str | None
    svid_status: str | None
    svid_not_before_epoch: int | None
    svid_not_after_epoch: int | None
    svid_chain_len: int | None
    svid_chain_authority_id: str | None
    svid_leaf_authority_id: str | None
    bundle_status: str | None
    bundle_authority_ids: list[str] | None
    agent_data_status: str | None
    agent_data_mtime_epoch: int | None
    anchor_status: str | None
    anchor_size_bytes: int | None
    anchor_mtime_epoch: int | None
    anchor_authority_ids: list[str] | None
    unmeasured: list[dict]
    raw: dict = field(repr=False, default_factory=dict)

    @property
    def at(self) -> str:
        return self.observed_at or str(self.observed_at_epoch)


def source_present(status: str | None, source: str, at: str) -> bool:
    """Read a source status as one of exactly three things.

    ``True``   the source answered and the value fields are usable.
    ``False``  the source answered about the target, and the answer is
               bad. Measured. A caller turns this into a violation.
    raises     nobody measured it, or the status is not one this reader
               knows. UNKNOWN.
    """
    if status is None:
        raise Unmeasured(f"{source}_status was not measured in the sample at {at}")
    if status == STATUS_OK:
        return True
    if status.startswith(TARGET_BAD_PREFIX):
        return False
    if status == STATUS_UNMEASURED:
        raise Unmeasured(f"{source} was not measured in the sample at {at}: probe said so")
    raise Unmeasured(
        f"{source}_status {status!r} in the sample at {at} is not a status this reader knows"
    )


@dataclass
class Judgement:
    name: str
    state: str
    violations: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    observations: dict = field(default_factory=dict)

    @property
    def reason(self) -> str:
        if self.state == FAIL:
            return self.violations[0] if self.violations else "measured and bad"
        if self.state == UNKNOWN:
            return self.gaps[0] if self.gaps else "not measured"
        return "held for every judged sample"


def settle(
    name: str,
    violations: list[str],
    gaps: list[str],
    observations: dict | None = None,
    *,
    empty_is_unknown: str | None = None,
) -> Judgement:
    """Fold one assurance. A violation outranks a gap.

    Order matters and it is the conservative one: if some samples are
    missing and the samples that exist show a real defect, the defect is
    the answer. The opposite order would let a gap in the series mask a
    measured failure, which is the failure mode the gap is supposed to
    protect against.
    """
    obs = observations or {}
    if violations:
        return Judgement(name, FAIL, violations, gaps, obs)
    if gaps:
        return Judgement(name, UNKNOWN, violations, gaps, obs)
    if empty_is_unknown:
        return Judgement(name, UNKNOWN, violations, [empty_is_unknown], obs)
    return Judgement(name, PASS, violations, gaps, obs)


# --------------------------------------------------------------- loading


def load_samples(paths: list[Path]) -> list[Sample]:
    samples: list[Sample] = []
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise Unreadable(f"cannot read sample log {path}: {exc}") from exc
        for lineno, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                # Not skipped. A line the reader cannot parse is a hole
                # in the series, and a hole that is silently stepped over
                # is indistinguishable from a series that was never
                # interrupted.
                raise Unreadable(f"{path}:{lineno} is not JSON: {exc}") from exc
            if not isinstance(obj, dict):
                raise Unreadable(f"{path}:{lineno} is not a JSON object")
            schema = obj.get("schema")
            if schema != SCHEMA_EXPECTED:
                raise Unreadable(
                    f"{path}:{lineno} has schema {schema!r}, not {SCHEMA_EXPECTED!r}; "
                    "a record this reader does not understand is not re-interpreted"
                )
            forbidden = sorted(FORBIDDEN_SAMPLE_KEYS & set(obj))
            if forbidden:
                raise Unreadable(
                    f"{path}:{lineno} carries {forbidden}: sample_carries_a_verdict. "
                    "The judgement is computed here from measured values; a sample that "
                    "arrives with an opinion is not read."
                )
            samples.append(_to_sample(obj, f"{path}:{lineno}"))
    samples.sort(key=lambda s: s.observed_at_epoch)
    return samples


def _to_sample(obj: dict, origin: str) -> Sample:
    def as_int(key):
        v = obj.get(key)
        if v is None:
            return None
        if not isinstance(v, int) or isinstance(v, bool):
            raise Unreadable(f"{origin}: {key} is {v!r}, not an integer")
        return v

    def as_str(key):
        v = obj.get(key)
        if v is None or v == "":
            return None
        if not isinstance(v, str):
            raise Unreadable(f"{origin}: {key} is {v!r}, not a string")
        return v

    def as_list(key):
        v = obj.get(key)
        if v is None:
            return None
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            raise Unreadable(f"{origin}: {key} is {v!r}, not a list of strings")
        return v

    at = as_int("observed_at_epoch")
    if at is None:
        raise Unreadable(f"{origin}: observed_at_epoch is missing; the sample has no place in a series")
    side = as_str("side")
    if side is None:
        raise Unreadable(f"{origin}: side is missing; the sample does not say what it describes")
    return Sample(
        observed_at_epoch=at,
        observed_at=obj.get("observed_at") or "",
        side=side,
        marker=as_str("marker"),
        svid_status=as_str("svid_status"),
        svid_not_before_epoch=as_int("svid_not_before_epoch"),
        svid_not_after_epoch=as_int("svid_not_after_epoch"),
        svid_chain_len=as_int("svid_chain_len"),
        svid_chain_authority_id=as_str("svid_chain_authority_id"),
        svid_leaf_authority_id=as_str("svid_leaf_authority_id"),
        bundle_status=as_str("bundle_status"),
        bundle_authority_ids=as_list("bundle_authority_ids"),
        agent_data_status=as_str("agent_data_status"),
        agent_data_mtime_epoch=as_int("agent_data_mtime_epoch"),
        anchor_status=as_str("anchor_status"),
        anchor_size_bytes=as_int("anchor_size_bytes"),
        anchor_mtime_epoch=as_int("anchor_mtime_epoch"),
        anchor_authority_ids=as_list("anchor_authority_ids"),
        unmeasured=obj.get("unmeasured") or [],
        raw=obj,
    )


# -------------------------------------------------------------- episodes


@dataclass(frozen=True)
class Episode:
    kind: str
    start: int
    end: int | None

    def contains(self, epoch: int) -> bool:
        if epoch < self.start:
            return False
        if self.end is None:
            return True
        return epoch <= self.end


def find_episodes(samples: list[Sample]) -> tuple[list[Episode], list[str]]:
    """Pair up the episode markers. An unpaired start is reported."""
    pairs = {
        "cold-agent": ("cold-agent-stop", "cold-agent-start"),
        "negative-control": ("negative-control-start", "negative-control-end"),
    }
    episodes: list[Episode] = []
    problems: list[str] = []
    for kind, (open_marker, close_marker) in pairs.items():
        open_at: int | None = None
        for s in samples:
            if s.marker == open_marker:
                if open_at is not None:
                    problems.append(
                        f"{kind}: a second {open_marker} at {s.at} before the previous one was closed"
                    )
                open_at = s.observed_at_epoch
            elif s.marker == close_marker:
                if open_at is None:
                    problems.append(f"{kind}: {close_marker} at {s.at} without a preceding {open_marker}")
                    continue
                episodes.append(Episode(kind, open_at, s.observed_at_epoch))
                open_at = None
        if open_at is not None:
            episodes.append(Episode(kind, open_at, None))
            problems.append(
                f"{kind}: {open_marker} at epoch {open_at} was never closed; every later sample is "
                "excluded from the standing assurances, so the window cannot be judged"
            )
    return episodes, problems


def in_any_episode(epoch: int, episodes: list[Episode]) -> bool:
    return any(e.contains(epoch) for e in episodes)


# ------------------------------------------------------------ assurances


def judge_z1(samples: list[Sample]) -> Judgement:
    """The authority that issued the SVID is in the *current* bundle.

    Rules out a substrate that is serving identities signed by a root
    the server has already pruned -- which is the state the May
    configuration reached within a day and held for four months.

    The comparison is made on the top of the SVID chain, not on the leaf.
    Under ``UpstreamAuthority "disk"`` the chain is leaf + intermediate
    and the bundle holds the long-lived root, so the leaf's own issuer
    is legitimately absent from the bundle; under a self-signed server
    the chain is the leaf alone and the two coincide.
    """
    violations, gaps = [], []
    seen = 0
    for s in samples:
        try:
            if not source_present(s.svid_status, "svid", s.at):
                violations.append(f"{s.at}: no SVID was served ({s.svid_status})")
                continue
            if not source_present(s.bundle_status, "bundle", s.at):
                violations.append(f"{s.at}: the server produced no authority set ({s.bundle_status})")
                continue
            authority = require_measured("svid_chain_authority_id", s.svid_chain_authority_id, s.at)
            bundle = require_measured("bundle_authority_ids", s.bundle_authority_ids, s.at)
        except Unmeasured as exc:
            gaps.append(str(exc))
            continue
        seen += 1
        if authority not in bundle:
            violations.append(
                f"{s.at}: the SVID chain terminates at authority {authority}, which is not one of "
                f"the {len(bundle)} authorities the server currently holds"
            )
    return settle(
        "Z1 issuing authority is in the current bundle",
        violations,
        gaps,
        {"samples_judged": seen},
        empty_is_unknown=(
            None
            if seen
            else "no sample outside the deliberate episodes could be judged"
        ),
    )


def judge_z2(samples: list[Sample], max_stall: int) -> Judgement:
    """The expiry moves. A cache does not move.

    The whole acceptance rests here. Every other signal this substrate
    produced in May was true while nothing was happening.
    """
    violations, gaps = [], []
    series: list[tuple[int, int]] = []
    for s in samples:
        try:
            if not source_present(s.svid_status, "svid", s.at):
                violations.append(
                    f"{s.at}: no SVID was served ({s.svid_status}); an expiry that does not exist "
                    "cannot move"
                )
                continue
            not_after = require_measured("svid_not_after_epoch", s.svid_not_after_epoch, s.at)
        except Unmeasured as exc:
            gaps.append(str(exc))
            continue
        series.append((s.observed_at_epoch, not_after))

    if len(series) < 2:
        gaps.append("fewer than two samples carry an expiry; movement cannot be established from one point")
        return settle("Z2 the SVID expiry moves", violations, gaps)

    last_move_at = series[0][0]
    moves = 0
    worst_stall = 0
    for (t_prev, e_prev), (t_now, e_now) in zip(series, series[1:]):
        if e_now < e_prev:
            violations.append(
                f"at {t_now} the SVID expiry moved backwards ({e_prev} -> {e_now}); an identity was "
                "replaced by an older one"
            )
            continue
        if e_now > e_prev:
            moves += 1
            last_move_at = t_now
        else:
            stall = t_now - last_move_at
            worst_stall = max(worst_stall, stall)
            if stall > max_stall:
                violations.append(
                    f"the SVID expiry did not move for {stall}s up to {t_now} (limit {max_stall}s); "
                    "this is what a credential served from a cache looks like"
                )
    trailing = series[-1][0] - last_move_at
    worst_stall = max(worst_stall, trailing)
    if trailing > max_stall:
        violations.append(
            f"the SVID expiry has not moved for the last {trailing}s of the window (limit {max_stall}s)"
        )
    span = series[-1][0] - series[0][0]
    if moves == 0 and span <= max_stall:
        # Not a violation. A series shorter than the tolerance has not
        # yet reached the point at which a movement was due, and calling
        # that a stalled credential would be a verdict about the sampling
        # rather than about the substrate. The trailing-stall check above
        # covers every series that is long enough to mean something.
        gaps.append(
            f"the series spans {span}s, not more than the {max_stall}s tolerance; the absence of a "
            "renewal in it does not establish anything yet"
        )
    return settle(
        "Z2 the SVID expiry moves",
        violations,
        gaps,
        {"renewals_observed": moves, "worst_stall_seconds": worst_stall, "span_seconds": span},
    )


def judge_z3(samples: list[Sample], min_span: int) -> Judgement:
    """``agent-data.json`` moves. The number that stood still for four months."""
    violations, gaps = [], []
    series: list[tuple[int, int]] = []
    for s in samples:
        try:
            if not source_present(s.agent_data_status, "agent_data", s.at):
                violations.append(f"{s.at}: the agent state file is not there ({s.agent_data_status})")
                continue
            mtime = require_measured("agent_data_mtime_epoch", s.agent_data_mtime_epoch, s.at)
        except Unmeasured as exc:
            gaps.append(str(exc))
            continue
        series.append((s.observed_at_epoch, mtime))

    if len(series) < 2:
        gaps.append("fewer than two samples carry the state-file mtime")
        return settle("Z3 the agent state file moves", violations, gaps)

    moves = 0
    worst_stall = 0
    last_move_at = series[0][0]
    for (_, m_prev), (t_now, m_now) in zip(series, series[1:]):
        if m_now < m_prev:
            violations.append(
                f"at {t_now} the state-file mtime went backwards ({m_prev} -> {m_now}); the volume was "
                "written by something other than the agent"
            )
        elif m_now > m_prev:
            moves += 1
            last_move_at = t_now
        else:
            worst_stall = max(worst_stall, t_now - last_move_at)
    span = series[-1][0] - series[0][0]
    worst_stall = max(worst_stall, series[-1][0] - last_move_at)
    if moves == 0:
        if span > min_span:
            violations.append(
                f"the agent state file did not change once in {span}s; this is the exact measurement "
                "that read May for 127 days"
            )
        else:
            # SPIRE does not document a write cadence for this file, so
            # a short series that shows no write is not yet evidence of
            # anything. Said out loud rather than folded into a pass.
            gaps.append(
                f"the series spans {span}s, not more than the {min_span}s floor; the absence of a "
                "state write in it does not establish anything yet"
            )
    return settle(
        "Z3 the agent state file moves",
        violations,
        gaps,
        {"state_writes_observed": moves, "worst_stall_seconds": worst_stall, "span_seconds": span},
    )


def judge_z4(samples: list[Sample], restage_max: int) -> Judgement:
    """The staged bootstrap anchor exists, matches, and stays fresh.

    Not in the CTO decision paper's §6.2. It is here for two reasons.
    ADR-0076's own risk section says the re-staging timer must be part
    of the probe or the class repeats; and the mandatory negative
    control -- an emptied ``bundles`` volume must come out red -- has
    nothing to turn red without this assurance, because a running agent
    keeps serving from its cache when the anchor is deleted. Z1..Z3
    would all stay green over an emptied volume. That is not a
    hypothetical: it is the May failure mode, and it is why a negative
    control was demanded in the first place.
    """
    violations, gaps = [], []
    seen = 0
    mtimes: list[tuple[int, int]] = []
    for s in samples:
        try:
            if not source_present(s.anchor_status, "anchor", s.at):
                violations.append(f"{s.at}: the staged bootstrap anchor is not usable ({s.anchor_status})")
                continue
            anchor_ids = require_measured("anchor_authority_ids", s.anchor_authority_ids, s.at)
            mtime = require_measured("anchor_mtime_epoch", s.anchor_mtime_epoch, s.at)
            if not source_present(s.bundle_status, "bundle", s.at):
                violations.append(f"{s.at}: the server produced no authority set ({s.bundle_status})")
                continue
            bundle_ids = require_measured("bundle_authority_ids", s.bundle_authority_ids, s.at)
        except Unmeasured as exc:
            gaps.append(str(exc))
            continue
        seen += 1
        if not set(anchor_ids) & set(bundle_ids):
            violations.append(
                f"{s.at}: the staged anchor holds {sorted(anchor_ids)} and the server holds "
                f"{sorted(bundle_ids)}; they share nothing, so a cold agent would bootstrap against "
                "an authority that no longer signs anything"
            )
        mtimes.append((s.observed_at_epoch, mtime))

    worst_stall = 0
    if len(mtimes) >= 2:
        last_move_at = mtimes[0][0]
        for (_, m_prev), (t_now, m_now) in zip(mtimes, mtimes[1:]):
            if m_now > m_prev:
                last_move_at = t_now
            else:
                worst_stall = max(worst_stall, t_now - last_move_at)
        worst_stall = max(worst_stall, mtimes[-1][0] - last_move_at)
        if worst_stall > restage_max:
            violations.append(
                f"the staged anchor was not rewritten for {worst_stall}s (limit {restage_max}s); the "
                "re-staging timer is the silent obligation ADR-0076 named, and it is not running"
            )
    elif mtimes:
        gaps.append("fewer than two samples carry the anchor mtime; re-staging cadence not established")

    return settle(
        "Z4 the staged bootstrap anchor is present, matching and fresh",
        violations,
        gaps,
        {"worst_restage_stall_seconds": worst_stall, "samples_judged": seen},
        empty_is_unknown=(
            None
            if seen or violations
            else "no sample outside the deliberate episodes carries an anchor measurement"
        ),
    )


def judge_f1(samples: list[Sample], min_rotations: int, rotation_period: int) -> Judgement:
    """Rotations of the signing authority, survived.

    What rotates under ADR-0076's configuration is the signing
    intermediate, once per ``ca_ttl`` -- the root is the long-lived
    ``UpstreamAuthority`` one and stands still by design. So the counter
    is the identity of the authority that signed the *leaf*, and the
    bundle-set transitions are reported next to it without being gated
    on: under the chosen configuration they are expected to read zero,
    and gating on them would demand an event the design forbids.

    "Survived" is not a synonym for "happened": each transition is
    required to be followed by a sample in which the chain still
    terminates inside the current bundle.
    """
    violations, gaps = [], []
    seq: list[tuple[Sample, str, bool]] = []
    for s in samples:
        try:
            if not source_present(s.svid_status, "svid", s.at):
                continue  # Z1/Z2 already carry this; F1 only counts what it can see
            signer = require_measured("svid_leaf_authority_id", s.svid_leaf_authority_id, s.at)
            if not source_present(s.bundle_status, "bundle", s.at):
                continue
            chain_auth = require_measured("svid_chain_authority_id", s.svid_chain_authority_id, s.at)
            bundle = require_measured("bundle_authority_ids", s.bundle_authority_ids, s.at)
        except Unmeasured as exc:
            gaps.append(str(exc))
            continue
        seq.append((s, signer, chain_auth in bundle))

    if len(seq) < 2:
        gaps.append(
            "fewer than two samples carry a signing authority; a rotation is a change between two "
            "observations and there are not two"
        )
        return settle("F1 at least six survived rotations", violations, gaps)

    transitions = 0
    survived = 0
    bundle_transitions = 0
    prev_bundle: set[str] | None = None
    for s in samples:
        if s.bundle_authority_ids is None:
            continue
        cur = set(s.bundle_authority_ids)
        if prev_bundle is not None and cur != prev_bundle:
            bundle_transitions += 1
        prev_bundle = cur

    for (_, prev_signer, _), (s_now, now_signer, ok_now) in zip(seq, seq[1:]):
        if now_signer == prev_signer:
            continue
        transitions += 1
        if ok_now:
            survived += 1
        else:
            violations.append(
                f"{s_now.at}: the signing authority rotated to {now_signer} and the SVID that followed "
                "does not chain to the current bundle; the rotation was not survived"
            )

    span = seq[-1][0].observed_at_epoch - seq[0][0].observed_at_epoch
    required_span = min_rotations * rotation_period
    if transitions < min_rotations:
        if span >= required_span:
            violations.append(
                f"{transitions} signing-authority rotations were observed in {span}s, fewer than the "
                f"{min_rotations} ADR-0076 requires. A window in which nothing could have gone wrong "
                "has not shown that nothing does"
            )
        else:
            # Too short for the count to be a finding. A rotation is due
            # once per ca_ttl; demanding six of them from a series that
            # cannot contain six would make the judgement a statement
            # about the length of the log.
            gaps.append(
                f"the series spans {span}s and six rotations at one per {rotation_period}s need "
                f"{required_span}s; the count is not yet a finding"
            )
    return settle(
        "F1 at least six survived rotations",
        violations,
        gaps,
        {
            "signing_authority_rotations": transitions,
            "rotations_survived": survived,
            "bundle_authority_set_transitions": bundle_transitions,
            "span_seconds": span,
        },
    )


def judge_f2(samples: list[Sample], episodes: list[Episode], ca_overlap: int) -> Judgement:
    """The cold-agent counter-probe.

    Stop the agent, wait out the CA overlap, start it again without
    touching a volume. It has to come back -- and "come back" means a
    *new* credential, not the one it had before, because the one it had
    before is exactly what a cache would still be serving.

    The one thing this judgement can check about "without touching a
    volume" is whether the agent's state file moved while the agent was
    down. Whether anything else on the node was touched is not knowable
    from here and is named in the test plan as an operator obligation,
    not asserted as if it were measured.
    """
    violations, gaps = [], []
    cold = [e for e in episodes if e.kind == "cold-agent"]
    if not cold:
        return Judgement(
            "F2 cold-agent counter-probe",
            UNKNOWN,
            [],
            ["no cold-agent episode is recorded in the window; the falsification was not performed"],
            {"episodes": 0},
        )

    for episode in cold:
        if episode.end is None:
            gaps.append(f"a cold-agent episode opened at {episode.start} was never closed")
            continue
        duration = episode.end - episode.start
        if duration < ca_overlap:
            violations.append(
                f"the agent was down for {duration}s, less than the {ca_overlap}s CA overlap; a restart "
                "inside the overlap proves nothing about the bootstrap anchor"
            )

        before = [
            s
            for s in samples
            if s.observed_at_epoch <= episode.start and s.svid_not_after_epoch is not None
        ]
        after = [
            s
            for s in samples
            if s.observed_at_epoch >= episode.end
            and s.svid_status == STATUS_OK
            and s.svid_not_after_epoch is not None
        ]
        if not before:
            gaps.append("no expiry was measured before the cold-agent episode; there is nothing to compare to")
            continue
        if not after:
            violations.append(
                "the agent served no SVID after the cold restart; it did not come back"
            )
            continue
        pre = before[-1]
        post = after[0]
        if post.svid_not_after_epoch <= pre.svid_not_after_epoch:
            violations.append(
                f"after the cold restart the SVID expiry is {post.svid_not_after_epoch}, no later than "
                f"the {pre.svid_not_after_epoch} it held before; the agent did not obtain a new "
                "credential, it re-served an old one"
            )
        try:
            if not source_present(post.bundle_status, "bundle", post.at):
                violations.append(f"{post.at}: the server produced no authority set after the restart")
            else:
                auth = require_measured("svid_chain_authority_id", post.svid_chain_authority_id, post.at)
                bundle = require_measured("bundle_authority_ids", post.bundle_authority_ids, post.at)
                if auth not in bundle:
                    violations.append(
                        f"{post.at}: after the cold restart the chain terminates at {auth}, which the "
                        "server does not hold"
                    )
        except Unmeasured as exc:
            gaps.append(str(exc))

        stop_sample = next((s for s in samples if s.observed_at_epoch == episode.start), None)
        start_sample = next((s for s in samples if s.observed_at_epoch == episode.end), None)
        if (
            stop_sample is not None
            and start_sample is not None
            and stop_sample.agent_data_mtime_epoch is not None
            and start_sample.agent_data_mtime_epoch is not None
            and start_sample.agent_data_mtime_epoch != stop_sample.agent_data_mtime_epoch
        ):
            violations.append(
                "the agent state file changed while the agent was stopped; the volume was touched "
                "during the counter-probe, and a counter-probe with a helping hand in it is not one"
            )

    return settle(
        "F2 cold-agent counter-probe",
        violations,
        gaps,
        {"episodes": len(cold)},
    )


def judge_negative_control(
    samples: list[Sample], episodes: list[Episode], restage_max: int, min_absent: int
) -> Judgement:
    """The mandatory negative control: an emptied ``bundles`` volume must come out red.

    Implemented by running the anchor assurance over the marked slice
    and *requiring* it to fail. A control that comes out green, or that
    comes out ``UNKNOWN``, invalidates the green window with it.

    The TV-PROV-6 lesson is wired in rather than written down: a control
    that removes the state it is supposed to test cannot see the thing
    it was built for. Here that shape would be a control run in which
    the probe itself stopped working -- then the anchor reads
    "unmeasured", the slice reads ``UNKNOWN``, and one could be tempted
    to accept "not green" as "red". It is not accepted. The slice has to
    contain at least one sample in which the *other* sources were still
    measured, so that the red is attributable to the emptied volume and
    not to a probe that fell over.
    """
    controls = [e for e in episodes if e.kind == "negative-control"]
    if not controls:
        return Judgement(
            "NC the negative control goes red",
            UNKNOWN,
            [],
            [
                "no negative-control episode is recorded; ADR-0076 makes it mandatory, and without it "
                "the green result is not worth anything either"
            ],
            {"episodes": 0},
        )

    violations, gaps = [], []
    absent_total = 0
    episode_total = 0
    for episode in controls:
        if episode.end is None:
            gaps.append(f"a negative-control episode opened at {episode.start} was never closed")
            continue
        slice_ = [s for s in samples if episode.contains(s.observed_at_epoch)]
        if not slice_:
            gaps.append("the negative-control episode contains no samples")
            continue
        still_measuring = [
            s
            for s in slice_
            if s.svid_status is not None
            and not s.svid_status.startswith(STATUS_UNMEASURED)
            and s.bundle_status == STATUS_OK
        ]
        if not still_measuring:
            gaps.append(
                "during the negative control no other source was measured; the control removed the "
                "measurement it was supposed to test, so its red cannot be attributed to the emptied "
                "volume"
            )
            continue
        absent = [
            s
            for s in slice_
            if s.anchor_status is not None
            and s.anchor_status.startswith(TARGET_BAD_PREFIX)
        ]
        absent_total += len(absent)
        episode_total += len(slice_)

        # Three outcomes, and the first two are the reason this block
        # was rewritten.
        #
        # The staged anchor is restored by a re-staging timer running
        # well under ca_ttl -- 30 minutes against an hourly probe. An
        # operator who removes the anchor without stopping that timer
        # gets it back before a single sample can see it gone. The slice
        # then contains no absent anchor, judge_z4 over it reads PASS,
        # and the old code called that "the control did not go red" and
        # failed the whole window on day seven.
        #
        # That sentence was wrong twice. The control did not fail to go
        # red; it was never carried out -- and the finding is about the
        # procedure, not about the instrument. "Nobody performed the
        # control" and "the control was performed and the instrument
        # could not see it" are different statements, and this file
        # exists to keep exactly that pair apart.
        if not absent:
            gaps.append(
                "the negative control was marked but no sample in it ever saw the anchor missing. "
                "The most likely cause is that the re-staging timer was left running and put the "
                "anchor back before the next sample: it restores on a cadence far below the probe's. "
                "Stop the re-staging timer before removing the anchor, and start it again afterwards"
            )
            continue
        if len(absent) < min_absent:
            gaps.append(
                f"the negative control saw the anchor missing in only {len(absent)} of {len(slice_)} "
                f"samples, fewer than the {min_absent} the procedure asks for. Most likely the "
                "re-staging timer put it back mid-control. The control has to outlast the restore "
                "cadence or it measures the timer instead of the assurance"
            )
            continue

        inner = judge_z4(slice_, restage_max)
        if inner.state != FAIL:
            # Defensive, and kept although judge_z4 cannot currently
            # reach it: an absent anchor is a violation there, so this
            # branch is unreachable today. It is the assertion the whole
            # mechanism rests on -- that the instrument fails when the
            # thing it watches is taken away -- and an assertion that is
            # only true because of how some other function happens to be
            # written today is exactly the kind that stops being true
            # quietly.
            violations.append(
                f"the negative control came out {inner.state}, not FAIL, although the anchor was "
                f"measured as missing in {len(absent)} samples: {inner.reason}. A check that cannot "
                "fail has not passed either, and the green window falls with it"
            )
    return settle(
        "NC the negative control goes red",
        violations,
        gaps,
        {
            "episodes": len(controls),
            "samples_in_episodes": episode_total,
            "samples_with_anchor_absent": absent_total,
        },
    )


def judge_coverage(
    samples: list[Sample],
    judged: list[Sample],
    episodes: list[Episode],
    window_seconds: int,
    max_gap: int,
) -> Judgement:
    """Was there enough window, and was it continuously observed?

    Gaps that fall inside a deliberate episode are not counted against
    the series -- the agent is meant to be down there.
    """
    violations, gaps = [], []
    if len(samples) < 2:
        return Judgement(
            "C window coverage",
            UNKNOWN,
            [],
            ["fewer than two samples; there is no window to speak of"],
            {"samples": len(samples)},
        )
    span = samples[-1].observed_at_epoch - samples[0].observed_at_epoch
    if span < window_seconds:
        gaps.append(
            f"the samples span {span}s, less than the {window_seconds}s window; the window is not over"
        )
    worst_gap = 0
    for prev, now in zip(samples, samples[1:]):
        gap = now.observed_at_epoch - prev.observed_at_epoch
        if gap <= max_gap:
            continue
        if in_any_episode(prev.observed_at_epoch, episodes) or in_any_episode(
            now.observed_at_epoch, episodes
        ):
            continue
        worst_gap = max(worst_gap, gap)
        gaps.append(
            f"no sample for {gap}s between {prev.at} and {now.at} (limit {max_gap}s); the substrate was "
            "unobserved for that stretch and nothing is claimed about it"
        )
    if samples and len(judged) * 2 < len(samples):
        gaps.append(
            f"only {len(judged)} of {len(samples)} samples fall outside the deliberate episodes; more of "
            "the window is excluded than judged"
        )
    return settle(
        "C window coverage",
        violations,
        gaps,
        {
            "samples": len(samples),
            "judged": len(judged),
            "span_seconds": span,
            "worst_unexplained_gap_seconds": worst_gap,
        },
    )


# ------------------------------------------------------------------ main


def evaluate(samples: list[Sample], args) -> tuple[str, list[Judgement], list[str]]:
    episodes, episode_problems = find_episodes(samples)
    judged = [s for s in samples if not in_any_episode(s.observed_at_epoch, episodes)]

    judgements = [
        judge_z1(judged),
        judge_z2(judged, args.z2_max_stall_seconds),
        judge_z3(judged, args.z3_min_span_seconds),
        judge_z4(judged, args.anchor_restage_max_seconds),
        judge_f1(judged, args.min_rotations, args.rotation_period_seconds),
        judge_f2(samples, episodes, args.ca_overlap_seconds),
        judge_negative_control(
            samples,
            episodes,
            args.anchor_restage_max_seconds,
            args.negative_control_min_absent_samples,
        ),
        judge_coverage(samples, judged, episodes, args.window_seconds, args.max_sample_gap_seconds),
    ]

    # An episode that was opened and never closed excludes every later
    # sample from the standing assurances. Whatever those assurances then
    # say is a statement about an arbitrary prefix of the window, not
    # about the window -- including a FAIL, which would most likely be
    # F1 counting rotations it was not allowed to see. So an open episode
    # forces UNKNOWN outright rather than letting an artefact of the
    # exclusion be reported as a finding. Nothing green can be bought
    # this way either: UNKNOWN is not a pass.
    open_episode = any(e.end is None for e in episodes)

    if open_episode:
        verdict = UNKNOWN
    elif any(j.state == FAIL for j in judgements):
        verdict = FAIL
    elif episode_problems or any(j.state == UNKNOWN for j in judgements):
        verdict = UNKNOWN
    else:
        verdict = PASS
    return verdict, judgements, episode_problems


def render_text(side: str, verdict: str, judgements: list[Judgement], problems: list[str]) -> str:
    lines = [f"ADR-0076 acceptance window — side {side}", ""]
    for j in judgements:
        lines.append(f"  [{j.state:<7}] {j.name}")
        lines.append(f"            {j.reason}")
        if j.observations:
            obs = ", ".join(f"{k}={v}" for k, v in sorted(j.observations.items()))
            lines.append(f"            observed: {obs}")
        for extra in j.violations[1:]:
            lines.append(f"            also: {extra}")
        for extra in j.gaps[: 3 if j.state != PASS else 0]:
            if extra != j.reason:
                lines.append(f"            gap:  {extra}")
    if problems:
        lines.append("")
        lines.append("  episode problems:")
        for p in problems:
            lines.append(f"    - {p}")
    lines.append("")
    if verdict == PASS:
        lines.append("  VERDICT: PASS — seven days, measured, with both falsifications performed.")
    elif verdict == FAIL:
        lines.append("  VERDICT: FAIL — measured, and bad.")
    else:
        lines.append(
            "  VERDICT: UNKNOWN — not measured. This is not a pass. "
            "The absence of a measurement is not a passed measurement."
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--samples", action="append", required=True, type=Path,
                   help="NDJSON sample log written by substrate-acceptance-probe.sh (repeatable)")
    p.add_argument("--side", default=None, help="only judge samples carrying this side label")
    p.add_argument("--window-seconds", type=int, default=DEFAULT_WINDOW_SECONDS)
    p.add_argument("--svid-ttl-seconds", type=int, default=DEFAULT_SVID_TTL_SECONDS)
    p.add_argument("--probe-interval-seconds", type=int, default=DEFAULT_PROBE_INTERVAL_SECONDS)
    p.add_argument("--z2-max-stall-seconds", type=int, default=None,
                   help="default: svid-ttl + probe-interval. Hourly sampling against a one-hour TTL "
                        "cannot resolve a single missed renewal; the tolerance says so out loud "
                        "instead of pretending to a precision the cadence does not have")
    p.add_argument("--z3-min-span-seconds", type=int, default=DEFAULT_Z3_MIN_SPAN_SECONDS,
                   help="how long a series has to be before the absence of a state-file write counts "
                        "as a finding. SPIRE documents no write cadence for agent-data.json, so a "
                        "short quiet stretch is a gap in the evidence and not a defect in the agent")
    p.add_argument("--anchor-restage-max-seconds", type=int, default=DEFAULT_ANCHOR_RESTAGE_MAX_SECONDS)
    p.add_argument("--ca-overlap-seconds", type=int, default=DEFAULT_CA_OVERLAP_SECONDS)
    p.add_argument("--min-rotations", type=int, default=DEFAULT_MIN_ROTATIONS)
    p.add_argument("--rotation-period-seconds", type=int, default=DEFAULT_ROTATION_PERIOD_SECONDS,
                   help="the cadence at which the signing authority is expected to turn over; "
                        "ADR-0076 keeps ca_ttl at 24h precisely so that this happens six times "
                        "inside the window")
    p.add_argument("--max-sample-gap-seconds", type=int, default=None,
                   help="default: three probe intervals")
    p.add_argument(
        "--negative-control-min-absent-samples",
        type=int,
        default=DEFAULT_NEGATIVE_CONTROL_MIN_ABSENT,
        help="how many samples inside the marked negative control must actually see the anchor "
             "missing. Below this the control did not outlast the re-staging timer and the run is "
             "UNKNOWN: a control the restore cadence undid has measured the timer, not the assurance",
    )
    p.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.z2_max_stall_seconds is None:
        args.z2_max_stall_seconds = args.svid_ttl_seconds + args.probe_interval_seconds
    if args.max_sample_gap_seconds is None:
        args.max_sample_gap_seconds = 3 * args.probe_interval_seconds

    try:
        samples = load_samples(args.samples)
    except Unreadable as exc:
        payload = {"verdict": UNKNOWN, "reason": str(exc)}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"  VERDICT: UNKNOWN — the reader could not read its inputs: {exc}")
        return 2

    if args.side:
        samples = [s for s in samples if s.side == args.side]
    sides = sorted({s.side for s in samples})
    if len(sides) > 1:
        msg = (
            f"the sample logs carry more than one side ({sides}); judge one side at a time with "
            "--side, because a window is a statement about a substrate and these are two"
        )
        if args.json:
            print(json.dumps({"verdict": UNKNOWN, "reason": msg}, indent=2, sort_keys=True))
        else:
            print(f"  VERDICT: UNKNOWN — {msg}")
        return 2

    side = sides[0] if sides else (args.side or "(none)")
    verdict, judgements, problems = evaluate(samples, args)

    if args.json:
        print(
            json.dumps(
                {
                    "schema": "wakir-runtime/substrate-acceptance-window@1",
                    "side": side,
                    "verdict": verdict,
                    "samples": len(samples),
                    "episode_problems": problems,
                    "judgements": [
                        {
                            "name": j.name,
                            "state": j.state,
                            "reason": j.reason,
                            "violations": j.violations,
                            "gaps": j.gaps,
                            "observations": j.observations,
                        }
                        for j in judgements
                    ],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_text(side, verdict, judgements, problems))

    return {PASS: 0, FAIL: 1, UNKNOWN: 2}[verdict]


if __name__ == "__main__":
    sys.exit(main())
