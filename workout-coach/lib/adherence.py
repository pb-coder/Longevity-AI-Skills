"""Prescription ledger: what the coach ASKED for, versus what happened.

Every other module in this package reads the tracker — the record of
what was performed. None of them read ``plans/<Person>/<date>-workout.md``,
so until this module existed the system had no memory of its own
prescriptions. Generation N could not differ from N−1 because it never
saw N−1; a movement could be prescribed six times and performed zero
times without anything noticing; and the 2026-07-25 "move the laggards
out of the tail" fix shipped with no way to find out whether it worked.
It did not.

What this module adds is one closed loop:

    plan markdown  ──parse──▶  prescription  ──reconcile──▶  adherence
         ▲                                                        │
         └────────────────  next generation reads  ◀──────────────┘

Public surface:

- ``parse_plan(text, plan_date)`` / ``parse_plan_file(path)`` — the plan
  markdown into per-workout, per-slot prescriptions.
- ``session_type_from_title(title)`` — ``lower`` / ``upper`` / ``full``
  / ``None`` off a workout heading.
- ``load_plans(person, today_d, limit)`` — the dated plan series, parsed,
  oldest first, never past the ``--today`` horizon.
- ``reconcile_plan(plan, window, rows, db, catalog)`` — one plan against
  the logs inside its own window.
- ``build_adherence(person, rows, db, today_d, catalog, history)`` — the
  ``adherence`` payload block, including the D5 bench list.
- ``dose_staleness(plans, catalog)`` — per carried exercise, whether its
  dose actually moved and for how many generations it has not.
- ``read_bench_log(person)`` / ``record_bench_response(...)`` — the D5
  answer store, so "ask once" means once and not once per run.

CLI (how an answer gets persisted; see ``record_bench_response``). Run
from the ``Skills/`` directory so the package facade resolves::

    python3 -m workout_coach.lib.adherence bench-list --person <Name>
    python3 -m workout_coach.lib.adherence bench-record --person <Name> \\
        --exercise "<Exercise>" --disposition retired --answer "<text>"
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from .parsing import _parse_iso_date
from .sessions import _is_working_set


# --------------------------------------------------------------- parsing
#
# The plan markdown is machine-written by /coach against a template that
# has not changed shape since 2026-05, so these patterns describe a
# format this repo controls, not one it guesses at. Anything that fails
# to match is reported through ``parse_errors`` rather than dropped —
# a silently unparsed slot is a prescription the ledger forgets, which
# is the exact failure being fixed.
#
# THE PLAN'S WORKOUT-HEADING GRAMMAR. Public, because it is not only the
# ledger's business: `render_validators` has to recognise exactly the
# headings this recognises, and a second copy of the pattern over there
# is how the two drift. Read it through `is_workout_heading` /
# `workout_heading_title` rather than matching the regex by hand.
#
# ``Deload Session`` and ``Session`` are not variant spellings, they are
# real headings the coach emits. Matching only ``Workout`` silently
# dropped whole plans: two of one person's fourteen parsed to zero
# prescribed slots, which reads downstream as "nothing was ever
# prescribed that week" rather than as a parse failure. The same
# inconsistency produced the opposite failure in the validator, where a
# `## Session N:` workout bypassed the core and arm checks entirely.
#
# The index accepts a LETTER as well as a number — `## Workout A: PUSH`
# is in the real corpus. It is a single character on purpose: widening it
# to `\w+` would swallow `## Workout Notes:` and similar prose headings.
WORKOUT_HEADING_RE = re.compile(
    r"^##\s+(Deload\s+Session|Workout|Session)\s+([0-9]+|[A-Za-z])\s*:\s*(.+?)\s*$",
    re.IGNORECASE)

# An H2 that talks about a workout or a session but does NOT match the
# grammar above. ``## Deload Workout 1:``, ``## Workout One:`` and
# ``## Workout 1 - LOWER A`` are all near misses, and a near miss is
# invisible: the section's bullets are skipped, and as long as ONE other
# workout in the file parses, ``parse_errors`` stays empty and a whole
# workout disappears from the ledger without a word. Reported, never
# silently accepted — the same failure class as the ``## Deload Session``
# bug this module was written to close.
_HEADING_NEAR_MISS_RE = re.compile(r"^##\s+.*\b(workout|session)\b",
                                   re.IGNORECASE)


def is_workout_heading(line: str) -> bool:
    """True when ``line`` opens a workout block in a plan markdown."""
    return bool(WORKOUT_HEADING_RE.match(line or ""))


def workout_heading_title(line: str) -> str | None:
    """``"Workout 1: LOWER A + CORE"`` for a workout heading, else ``None``.

    The display form — kind, index and title normalised back into one
    string — so a caller that only needs to name the section does not
    have to know the capture-group layout.
    """
    m = WORKOUT_HEADING_RE.match(line or "")
    if not m:
        return None
    return f"{m.group(1).strip()} {m.group(2)}: {m.group(3).strip()}"
_ANY_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_BULLET_RE = re.compile(r"^-\s+([^:]+?)\s*:\s*(.+?)\s*$")
# The indented em-dash continuation under a bullet: the plan's sparse
# per-slot note. It carries the superset pairing ("superset with the calf
# raise above"), which is the only place the plan states its own
# placement, so it is kept rather than skipped.
_NOTE_RE = re.compile(r"^\s+[—–-]\s*(.+?)\s*$")
_SUPERSET_RE = re.compile(
    r"superset(?:ted)?\s+(?:with|onto|into)\s+(?:the\s+)?(.+?)"
    r"(?:\s+(?:above|below|before|after))?\s*$", re.IGNORECASE)
# The plan's channel for the one anchor-change reason nothing can derive.
# ``stall_3_sessions`` comes off the e1RM stall counter and
# ``age_3_blocks`` off the block artifact, but only the user knows about
# an injury — and until this existed the rotation validator demanded a
# field the plan markdown had no way to express, so the sanctioned
# response to a four-session stall was unreachable.
_ANCHOR_CHANGE_RE = re.compile(
    r"anchor\s+change\s*:\s*(stall_3_sessions|injury|age_3_blocks)\b",
    re.IGNORECASE)

# A trailing per-side qualifier. It rides on a bodyweight rep count
# (``Dead Bug: 10 per side``) and, before this, made the whole item
# unparseable — three real core prescriptions in the live corpus counted
# as zero prescribed sets, on an emphasis muscle.
_PER_SIDE = r"(?:\s*(?:per|each|/)\s*(?:side|leg|arm|hand))?"

# One prescribed set, e.g. ``90kgx8-10``, ``52kgx8``, ``16kgx8-10 per side``.
_SET_LOAD_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*kg\s*[x×]\s*(\d+)(?:\s*[-–]\s*(\d+))?", re.IGNORECASE)
# A multiplied carry / interval, e.g. ``3 x 30m @ 24kg`` or ``3 x 45s``.
_SET_MULT_RE = re.compile(
    r"^\s*(\d+)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(m|s|sec|secs|min)\b"
    r"(?:\s*@\s*(\d+(?:\.\d+)?)\s*kg)?", re.IGNORECASE)
# ``4 x 8 @ 90kg`` / ``3 x 12`` — sets first, reps second, load last.
# The other form this file already knew (``90kgx8`` repeated with ///)
# writes one item per set; this one writes the set count up front, and
# not recognising it silently produced a bullet with zero prescribed
# sets and no error.
_SET_MULT_REPS_RE = re.compile(
    r"^\s*(\d+)\s*[x×]\s*(\d+)(?:\s*[-–]\s*(\d+))?\s*(?:reps?)?"
    r"(?:\s*@\s*(\d+(?:\.\d+)?)\s*kg)?" + _PER_SIDE + r"\s*$", re.IGNORECASE)
# A hold or a distance with no load, e.g. ``45s hold``, ``30m``.
_SET_TIME_RE = re.compile(
    r"^\s*(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds?|min|minutes?)\b", re.IGNORECASE)
# Bodyweight reps, e.g. ``10``, ``8-10``, ``15 reps``, ``10 per side``,
# ``bodyweight x 12``. The explicit bodyweight prefix matters now that
# three of the four movements W6a added to the catalog are ``[BW]``.
_SET_REPS_RE = re.compile(
    r"^\s*(?:(?:bodyweight|body\s*weight|bw)\s*[x×]\s*)?"
    r"(\d+)(?:\s*[-–]\s*(\d+))?\s*(?:reps?)?" + _PER_SIDE + r"\s*$",
    re.IGNORECASE)
_WARMUP_TOKEN_RE = re.compile(r"\(\s*warm[\s-]?up\s*\)", re.IGNORECASE)

_LOWER_TITLE_RE = re.compile(r"\b(lower|legs?|glutes?|posterior|hinge)\b", re.IGNORECASE)
_UPPER_TITLE_RE = re.compile(r"\b(upper|push|pull|chest|back|shoulders?|arms?)\b",
                             re.IGNORECASE)
_FULL_TITLE_RE = re.compile(r"\bfull[\s-]?body\b", re.IGNORECASE)


def session_type_from_title(title: str | None) -> str | None:
    """``lower`` / ``upper`` / ``full`` from a workout heading, else ``None``.

    The heading is the only place a plan states its own session type, and
    several downstream rules (the D3 core budget, block slot identity)
    are keyed on it. ``None`` is returned rather than a guess when the
    heading says neither — a wrong session type silently applies the
    wrong budget.
    """
    t = title or ""
    if _FULL_TITLE_RE.search(t):
        return "full"
    lower = bool(_LOWER_TITLE_RE.search(t))
    upper = bool(_UPPER_TITLE_RE.search(t))
    if lower and not upper:
        return "lower"
    if upper and not lower:
        return "upper"
    if lower and upper:
        return "full"
    return None


_SESSION_KEY_RE = re.compile(r"[^a-z0-9]+")


def session_key(title: str, index: int) -> str:
    """Stable identity for a workout, off its heading.

    ``"LOWER A + CORE"`` -> ``lower_a``. The ``+ CORE`` suffix is dropped
    because it names an inclusion, not a session type, and it moves
    around between generations; the leading identifier does not.

    The workout INDEX is not an identity — workout 3 of one plan and
    workout 3 of the next are frequently different sessions. Anything
    that tracks a session across generations (which sessions keep going
    undone; which slot a block rotation applies to) has to key on this
    instead. A heading that yields nothing usable falls back to
    ``workout_<n>``, which is stable within a plan but not across one.
    """
    head = (title or "").split("+")[0]
    slug = _SESSION_KEY_RE.sub("_", head.strip().lower()).strip("_")
    return slug or f"workout_{index}"


def _parse_set_item(item: str) -> dict | None:
    """One ``///``-separated prescription item into a typed set spec.

    Returns ``{"sets", "load_kg", "rep_lo", "rep_hi", "seconds",
    "metres", "is_warmup"}``, or ``None`` when the item is not
    recognisable as a prescription at all.

    A RECOGNISED item with no work in it — ``Rowing Machine: 3 min``, a
    minutes-denominated warmup or cardio bullet — comes back with
    ``sets: 0`` rather than as ``None``. The two used to be the same
    answer, which is why an unparseable bullet was indistinguishable
    from a deliberate zero and could not be reported.
    """
    raw = (item or "").strip()
    if not raw:
        return None
    is_warmup = bool(_WARMUP_TOKEN_RE.search(raw))
    body = _WARMUP_TOKEN_RE.sub("", raw).strip()

    m = _SET_LOAD_RE.match(body)
    if m:
        lo = int(m.group(2))
        hi = int(m.group(3)) if m.group(3) else lo
        return {"sets": 1, "load_kg": float(m.group(1)), "rep_lo": lo,
                "rep_hi": hi, "seconds": None, "metres": None,
                "is_warmup": is_warmup}

    m = _SET_MULT_RE.match(body)
    if m:
        unit = m.group(3).lower()
        val = float(m.group(2))
        return {"sets": int(m.group(1)),
                "load_kg": float(m.group(4)) if m.group(4) else None,
                "rep_lo": None, "rep_hi": None,
                "seconds": val * 60 if unit == "min" else (
                    val if unit in ("s", "sec", "secs") else None),
                "metres": val if unit == "m" else None,
                "is_warmup": is_warmup}

    m = _SET_MULT_REPS_RE.match(body)
    if m:
        lo = int(m.group(2))
        hi = int(m.group(3)) if m.group(3) else lo
        return {"sets": int(m.group(1)),
                "load_kg": float(m.group(4)) if m.group(4) else None,
                "rep_lo": lo, "rep_hi": hi, "seconds": None, "metres": None,
                "is_warmup": is_warmup}

    m = _SET_REPS_RE.match(body)
    if m:
        lo = int(m.group(1))
        hi = int(m.group(2)) if m.group(2) else lo
        return {"sets": 1, "load_kg": None, "rep_lo": lo, "rep_hi": hi,
                "seconds": None, "metres": None, "is_warmup": is_warmup}

    m = _SET_TIME_RE.match(body)
    if m:
        unit = m.group(2).lower()
        val = float(m.group(1))
        # A minutes-denominated bullet with no load is a cardio / warmup
        # machine entry ("Rowing Machine: 3 min"). Recognised, and
        # deliberately worth zero sets.
        if unit.startswith("min"):
            return {"sets": 0, "load_kg": None, "rep_lo": None,
                    "rep_hi": None, "seconds": val * 60, "metres": None,
                    "is_warmup": is_warmup}
        return {"sets": 1, "load_kg": None, "rep_lo": None, "rep_hi": None,
                "seconds": val, "metres": None, "is_warmup": is_warmup}
    return None


def _mode(values: list) -> object:
    """Most common value, ties broken by first occurrence. ``None`` if empty."""
    best, best_n = None, 0
    for v in values:
        n = values.count(v)
        if n > best_n:
            best, best_n = v, n
    return best


def _slot_from_bullet(exercise: str, spec: str, position: int) -> dict:
    """Build one prescription slot from ``- <exercise>: <spec>``.

    ``unparsed`` lists the ``///`` items that matched no prescription
    grammar at all. It is the difference between "this bullet prescribes
    nothing" and "this bullet prescribes something nobody read", and
    ``parse_plan`` turns the second into a reported error.
    """
    raw_items = [x for x in re.split(r"///", spec) if x.strip()]
    parsed = [(x, _parse_set_item(x)) for x in raw_items]
    unparsed = [x.strip() for x, i in parsed if i is None]
    items = [i for _x, i in parsed if i and i["sets"]]
    working = [i for i in items if not i["is_warmup"]]
    warmups = [i for i in items if i["is_warmup"]]
    loads = [i["load_kg"] for i in working if i["load_kg"] is not None]
    lo = [i["rep_lo"] for i in working if i["rep_lo"] is not None]
    hi = [i["rep_hi"] for i in working if i["rep_hi"] is not None]
    rep_lo = _mode(lo)
    rep_hi = _mode(hi)
    return {
        "exercise":        exercise.strip(),
        "position":        position,
        "prescribed_sets": sum(i["sets"] for i in working),
        "warmup_sets":     sum(i["sets"] for i in warmups),
        "load_kg":         _mode(loads),
        "rep_lo":          rep_lo,
        "rep_hi":          rep_hi,
        "rep_target":      (f"{rep_lo}-{rep_hi}" if rep_lo is not None
                            and rep_hi is not None and rep_hi != rep_lo
                            else (str(rep_lo) if rep_lo is not None else None)),
        "seconds":         _mode([i["seconds"] for i in working
                                  if i["seconds"] is not None]),
        "metres":          _mode([i["metres"] for i in working
                                  if i["metres"] is not None]),
        "notes":           [],
        "superset_hint":   None,
        "anchor_change_hint": None,
        "unparsed":        unparsed,
        "raw":             spec.strip(),
    }


def parse_plan(text: str, plan_date: str) -> dict:
    """Parse one plan markdown into its prescriptions.

    Returns ``{"plan_date", "workouts": [...], "parse_errors": [...]}``.
    Each workout is ``{"index", "title", "session_type", "slots": [...]}``
    and each slot the shape ``_slot_from_bullet`` returns.

    Only ``## Workout N:`` sections are walked. ``## Cardio N:`` bullets
    are prose ("Work: 5 x 3 min at HR 158bpm plus") and would parse into
    nonsense sets; a plan's cardio prescriptions are not reconciled here.

    NOTHING FAILS QUIETLY. Two whole-plan errors used to be the only
    output, and both are all-or-nothing: "no headings at all" and "no
    prescribed sets at all". A plan where ONE workout heading is
    misspelled, or ONE bullet is written in a form nobody parses, hit
    neither — the workout or the bullet simply vanished from the ledger
    and every downstream number silently shrank. Three narrower errors
    close that:

      * an H2 that names a workout or a session but misses the grammar
        (``## Deload Workout 1:``, ``## Workout One:``,
        ``## Workout 1 - LOWER A``);
      * a bullet that yields no sets and no warmup sets at all;
      * a bullet whose spec contains an item no grammar recognised, even
        when the rest of it parsed.
    """
    workouts: list[dict] = []
    errors: list[str] = []
    notes: list[str] = []
    current: dict | None = None
    position = 0
    for line in (text or "").splitlines():
        m = WORKOUT_HEADING_RE.match(line)
        if not m and _HEADING_NEAR_MISS_RE.match(line):
            errors.append(
                f"{plan_date}: heading {line.strip()!r} names a workout or a "
                f"session but does not match '## Workout N: TITLE', so its "
                f"bullets were not read")
        if m:
            # ``index`` is the workout's ORDINAL POSITION in the plan, not
            # the label it was given: the label may be a letter
            # (`## Workout A:`) and every consumer sorts and dict-keys on
            # this. The two agree for every plan in the corpus, which all
            # number contiguously from 1; ``label`` keeps the original
            # token for display.
            idx = len(workouts) + 1
            current = {
                "index":        idx,
                "label":        m.group(2),
                "title":        m.group(3).strip(),
                "session":      session_key(m.group(3), idx),
                "session_type": session_type_from_title(m.group(3)),
                "is_deload":    m.group(1).lower().startswith("deload"),
                "slots":        [],
            }
            workouts.append(current)
            position = 0
            continue
        if _ANY_H2_RE.match(line):
            current = None
            continue
        if current is None:
            continue
        b = _BULLET_RE.match(line)
        if not b:
            n = _NOTE_RE.match(line)
            if n and current["slots"]:
                slot = current["slots"][-1]
                slot["notes"].append(n.group(1))
                sup = _SUPERSET_RE.search(n.group(1))
                if sup and not slot["superset_hint"]:
                    slot["superset_hint"] = sup.group(1).strip()
                anc = _ANCHOR_CHANGE_RE.search(n.group(1))
                if anc and not slot["anchor_change_hint"]:
                    slot["anchor_change_hint"] = anc.group(1).lower()
            continue
        name, spec = b.group(1), b.group(2)
        position += 1
        slot = _slot_from_bullet(name, spec, position)
        where = f"{plan_date} {current['title']}"
        if slot["unparsed"]:
            errors.append(
                f"{where}: '{name.strip()}' — "
                f"{len(slot['unparsed'])} of "
                f"{len(slot['unparsed']) + slot['prescribed_sets'] + slot['warmup_sets']}"
                f" prescription item(s) matched no known form "
                f"({', '.join(repr(u) for u in slot['unparsed'][:3])}) and "
                f"counted as zero sets")
        elif slot["prescribed_sets"] == 0 and slot["warmup_sets"] == 0:
            # Recognised, and deliberately worth nothing: a warmup
            # machine bullet ("3 min") or a cue. Said out loud, but in
            # the quiet channel — nothing was lost here, and an error
            # that fires on every healthy plan is how a channel stops
            # being read.
            notes.append(
                f"{where}: '{name.strip()}: {spec.strip()}' prescribes no "
                f"working sets — read as a duration or cue, not as work")
        current["slots"].append(slot)
    if not workouts:
        errors.append(f"{plan_date}: no '## Workout N:' headings found")
    elif not any(s["prescribed_sets"] for w in workouts for s in w["slots"]):
        errors.append(f"{plan_date}: headings parsed but no prescribed sets")
    return {
        "plan_date":    plan_date,
        "is_deload":    any(w.get("is_deload") for w in workouts),
        "workouts":     workouts,
        # Two channels on purpose. `parse_errors` is "information was
        # lost here"; `parse_notes` is "this was read and is worth zero".
        "parse_errors": errors,
        "parse_notes":  notes,
    }


def parse_plan_file(path: Path, plan_date: str | None = None) -> dict:
    """``parse_plan`` on a file, inferring ``plan_date`` from the filename."""
    path = Path(path)
    if plan_date is None:
        plan_date = path.name[:10]
    return parse_plan(path.read_text(encoding="utf-8"), plan_date)


def load_plans(person: str, today_d: date, limit: int | None = None) -> list[dict]:
    """Parsed plan series for ``person``, oldest first.

    Plans dated after ``today_d`` are dropped: a backtest must not see a
    prescription that had not been written yet. ``limit`` keeps only the
    newest N (the ledger needs history for ``consecutive_unperformed``,
    but not all of it).
    """
    from shared.person_paths import list_workout_plans
    out: list[dict] = []
    for plan_date, path in list_workout_plans(person):
        d = _parse_iso_date(plan_date)
        if d is None or d > today_d:
            continue
        try:
            out.append(parse_plan_file(path, plan_date))
        except OSError as exc:                       # pragma: no cover - io
            out.append({"plan_date": plan_date, "workouts": [],
                        "parse_errors": [f"{plan_date}: unreadable ({exc})"],
                        "parse_notes": []})
    if limit is not None and limit > 0:
        out = out[-limit:]
    return out


# A plan nominally covers one week. Below that the newest window has not
# had time to be executed, and counting it toward the bench would retire
# a movement the day after prescribing it — the exact opposite of D5's
# "two unperformed prescriptions". The headline numbers still report the
# open window; only the bench history waits for it to close.
MIN_CLOSED_WINDOW_DAYS = 7


def plan_windows(plans: list[dict], today_d: date) -> list[tuple[dict, date, date]]:
    """Pair each plan with its ``[plan_date, next_plan_date)`` window.

    The last plan's window closes at ``today_d`` inclusive, expressed as
    an exclusive bound of ``today_d + 1`` so a session logged today
    counts. A plan is answerable only for the days it was the live plan.
    """
    out: list[tuple[dict, date, date]] = []
    for i, plan in enumerate(plans):
        start = _parse_iso_date(plan["plan_date"])
        if start is None:
            continue
        if i + 1 < len(plans):
            end = _parse_iso_date(plans[i + 1]["plan_date"]) or (today_d + timedelta(days=1))
        else:
            end = today_d + timedelta(days=1)
        out.append((plan, start, end))
    return out


# ----------------------------------------------------------- reconciling
def _catalog_meta(catalog: dict | None, exercise: str) -> dict:
    return (catalog or {}).get((exercise or "").strip().lower()) or {}


def _is_isolation(exercise: str, catalog: dict | None, db: dict | None) -> bool:
    """Isolation vs compound, read off the catalog's own section headings.

    The truncation signal this feeds is the load-bearing one: measured
    drop rate is 28% for isolation against 11% for compounds, which is
    why "move the laggards earlier in the session" failed twice. Position
    was never the variable.
    """
    meta = _catalog_meta(catalog, exercise)
    if meta.get("is_compound") is not None:
        return not meta["is_compound"]
    entry = (db or {}).get((exercise or "").strip().lower()) or {}
    return not entry.get("synergists")


def _logged_working_sets(rows: list[dict], db: dict,
                         start: date, end: date) -> dict[str, list[dict]]:
    """Working sets in ``[start, end)`` grouped by date, warmup/cardio removed.

    Warmup- and cardio-section catalog entries are dropped here for the
    same reason ``weekly_volume_per_muscle`` drops them: a plan's
    ``Jumping Jacks: 50`` is not a prescribed working set, so counting
    its log row would inflate both sides of the ratio.
    """
    by_date: dict[str, list[dict]] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        d = _parse_iso_date(r.get("date"))
        if d is None or d < start or d >= end:
            continue
        entry = db.get((r.get("exercise") or "").strip().lower())
        if entry and (entry.get("is_warmup") or entry.get("is_cardio")):
            continue
        by_date.setdefault(r["date"], []).append(r)
    return by_date


# A logged session is credited to the planned workout it overlaps most.
# Below this coverage the session is off-plan: crediting it anyway would
# let an unrelated session mark a planned workout "performed".
_SESSION_MATCH_MIN_COVERAGE = 0.34


def _match_sessions(plan: dict, sessions: dict[str, list[dict]]) -> dict:
    """Assign each logged session date to the planned workout it best covers.

    Returns ``{date: workout_index | None}``. Coverage is the share of
    the session's DISTINCT exercises that the planned workout also
    prescribes — not Jaccard, because a session that is a faithful
    partial execution of a planned workout (five of eight slots) should
    still match it, and Jaccard penalises exactly that.
    """
    planned: dict[int, set[str]] = {
        w["index"]: {s["exercise"].strip().lower()
                     for s in w["slots"] if s["prescribed_sets"] > 0}
        for w in plan.get("workouts") or []
    }
    out: dict[str, int | None] = {}
    for d, rws in sessions.items():
        names = {(r.get("exercise") or "").strip().lower() for r in rws}
        if not names:
            out[d] = None
            continue
        best_idx, best_cov = None, 0.0
        for idx, want in planned.items():
            if not want:
                continue
            cov = len(names & want) / len(names)
            if cov > best_cov:
                best_idx, best_cov = idx, cov
        out[d] = best_idx if best_cov >= _SESSION_MATCH_MIN_COVERAGE else None
    return out


def reconcile_plan(plan: dict, start: date, end: date, rows: list[dict],
                   db: dict, catalog: dict | None = None) -> dict:
    """One plan against the logs inside ``[start, end)``.

    Emits set counts, the per-exercise ledger, the workouts that never
    happened, and the substitutions — a same-muscle movement logged in
    place of the prescribed one. Substitutions are separated out because
    14% of apparent misses were exactly that, and counting them as skips
    benches movements the user did do.

    THE TESTED / UNTESTED SPLIT. A prescription inside a workout that
    never happened was not refused, it was never put to the question.
    Those are different facts about the user and only one of them says
    anything about the exercise. Each per-exercise row therefore carries
    ``tested_prescribed_sets`` (from workouts that WERE performed) beside
    the total, and ``tested`` says whether the row is evidence at all.
    Without the split, one skipped leg day retires every movement in it.

    Two completion rates fall out of that, and both are needed:

      ``completion_rate``        — all prescribed sets. Answers "did the
                                   plan happen", showing up included.
      ``tested_completion_rate`` — sets prescribed into performed
                                   sessions only. Answers "inside a
                                   session that did happen, what got
                                   cut".

    Neither is safe alone. The first shrinks if the coach prescribes
    less; the second flatters a coach that loads volume into sessions it
    expects to be skipped. Reported together they constrain each other.

    EXTRA SETS DO NOT PAY FOR MISSING ONES. Every rate here is computed
    on sets CREDITED, which is ``min(performed, prescribed)`` per
    exercise. The spec's success metric is "prescribed volume performed
    >= 85%" and an uncapped ratio does not measure that: one tracker read
    111% overall and 118% on isolation across four of twenty-six
    windows, with seven exercises individually above 1.0 — four extra
    curl sets silently covering four skipped shrug sets, on different
    muscles, in different sessions. ``performed_sets`` stays raw and
    ``overshoot_sets`` names the difference, so nothing is hidden; it is
    simply not allowed to cancel a miss.
    """
    sessions = _logged_working_sets(rows, db, start, end)
    match = _match_sessions(plan, sessions)
    performed_workouts = {v for v in match.values() if v is not None}

    prescribed: dict[str, dict] = {}
    for w in plan.get("workouts") or []:
        was_performed = w["index"] in performed_workouts
        for s in w["slots"]:
            if s["prescribed_sets"] <= 0:
                continue
            key = s["exercise"].strip().lower()
            # Warmup and cardio catalog entries are excluded on BOTH sides
            # of the ratio, exactly as ``weekly_volume_per_muscle`` excludes
            # them. `Jumping Jacks: 50` is a prescribed line but not a
            # prescribed working set, and counting it inflates the
            # denominator (and, once performed, the numerator) with work
            # nobody is measuring.
            cat = db.get(key) or {}
            if cat.get("is_warmup") or cat.get("is_cardio"):
                continue
            agg = prescribed.setdefault(key, {
                "name": s["exercise"].strip(), "prescribed_sets": 0,
                "tested_sets": 0, "slots": [], "workouts": set(),
                "missed_workouts": set(),
            })
            agg["prescribed_sets"] += s["prescribed_sets"]
            agg["slots"].append(s)
            agg["workouts"].add(w["index"])
            if was_performed:
                agg["tested_sets"] += s["prescribed_sets"]
            else:
                agg["missed_workouts"].add(w["index"])

    performed: dict[str, int] = {}
    off_plan: dict[str, int] = {}
    for d, rws in sessions.items():
        for r in rws:
            key = (r.get("exercise") or "").strip().lower()
            if key in prescribed:
                performed[key] = performed.get(key, 0) + 1
            else:
                off_plan[key] = off_plan.get(key, 0) + 1

    per_exercise = []
    for key, agg in sorted(prescribed.items()):
        done = performed.get(key, 0)
        tested = agg["tested_sets"]
        # Credited: extra sets of one movement are not evidence that a
        # different, skipped movement happened.
        credited = min(done, agg["prescribed_sets"])
        credited_tested = min(done, tested)
        per_exercise.append({
            "name":            agg["name"],
            "prescribed_sets": agg["prescribed_sets"],
            "tested_prescribed_sets": tested,
            "performed_sets":  done,
            "credited_sets":   credited,
            "overshoot_sets":  max(done - agg["prescribed_sets"], 0) or None,
            "completion_rate": round(credited / agg["prescribed_sets"], 3),
            "tested_completion_rate": (round(credited_tested / tested, 3)
                                       if tested else None),
            # False ≡ every workout holding this exercise went undone, so
            # the prescription is untested: neither performed nor refused.
            "tested":          tested > 0,
            "is_isolation":    _is_isolation(agg["name"], catalog, db),
            "workouts":        sorted(agg["workouts"]),
            "missed_workouts": sorted(agg["missed_workouts"]),
            "_credited_tested": credited_tested,
        })

    sets_prescribed = sum(e["prescribed_sets"] for e in per_exercise)
    sets_tested = sum(e["tested_prescribed_sets"] for e in per_exercise)
    sets_performed = sum(e["performed_sets"] for e in per_exercise)
    sets_credited = sum(e["credited_sets"] for e in per_exercise)
    sets_overshoot = sum(e["overshoot_sets"] or 0 for e in per_exercise)
    # The isolation-vs-compound split is a WITHIN-SESSION truncation
    # finding (28% against 11%), so it is computed on the tested subset.
    # Mixing in sessions that never happened measures attendance and
    # calls it truncation.
    iso_p = sum(e["tested_prescribed_sets"] for e in per_exercise
                if e["is_isolation"])
    iso_d = sum(e["_credited_tested"] for e in per_exercise
                if e["is_isolation"])
    credited_tested_total = sum(e["_credited_tested"] for e in per_exercise)
    cmp_p = sets_tested - iso_p
    cmp_d = credited_tested_total - iso_d
    for e in per_exercise:
        e.pop("_credited_tested", None)

    planned_idx = [w["index"] for w in plan.get("workouts") or []]
    by_index = {w["index"]: w for w in plan.get("workouts") or []}
    missed = []
    for idx in sorted(set(planned_idx) - performed_workouts):
        w = by_index[idx]
        missed.append({
            "index":        idx,
            "session":      w.get("session"),
            "title":        w.get("title"),
            "session_type": w.get("session_type"),
            "sets_prescribed": sum(s["prescribed_sets"] for s in w["slots"]),
        })

    return {
        "plan_date":        plan["plan_date"],
        "is_deload":        bool(plan.get("is_deload")),
        "window":           [start.isoformat(), (end - timedelta(days=1)).isoformat()],
        "window_days":      (end - start).days,
        "sessions_planned": len(planned_idx),
        "sessions_performed": len(performed_workouts),
        "sessions_logged":  len(sessions),
        "sessions_off_plan": sum(1 for v in match.values() if v is None),
        "workouts_never_done": sorted(set(planned_idx) - performed_workouts),
        "missed_sessions":  missed,
        "sets_prescribed":  sets_prescribed,
        "sets_prescribed_tested": sets_tested,
        "sets_performed":   sets_performed,
        # Sets that answered a prescription. `sets_performed` minus this
        # is extra work on movements that were already complete; it is
        # reported, and it does not pay for a skipped one.
        "sets_credited":    sets_credited,
        "sets_overshoot":   sets_overshoot or None,
        "sets_off_plan":    sum(off_plan.values()),
        "completion_rate":  (round(sets_credited / sets_prescribed, 3)
                             if sets_prescribed else None),
        "tested_completion_rate": (round(credited_tested_total / sets_tested, 3)
                                   if sets_tested else None),
        "isolation_completion_rate": (round(iso_d / iso_p, 3) if iso_p else None),
        "compound_completion_rate":  (round(cmp_d / cmp_p, 3) if cmp_p else None),
        "per_exercise":     per_exercise,
        "substitutions":    _detect_substitutions(
            plan, sessions, match, prescribed, performed, off_plan, db),
        "_match":           match,
    }


def _detect_substitutions(plan, sessions, match, prescribed, performed,
                          off_plan, db) -> list[dict]:
    """Same-muscle movements logged where a prescribed one was skipped.

    A substitution is not a skip. Detection is per matched session: a
    prescribed slot with zero performed sets, paired with an off-plan
    exercise logged in that same session that shares its primary muscle.
    Each off-plan exercise is claimed at most once so a single Leg
    Extension cannot excuse three different skipped quad slots.
    """
    by_index = {w["index"]: w for w in plan.get("workouts") or []}
    claimed: set[tuple[str, str]] = set()
    out: list[dict] = []
    for d, idx in sorted(match.items()):
        if idx is None or idx not in by_index:
            continue
        logged = {(r.get("exercise") or "").strip().lower() for r in sessions.get(d, [])}
        extras = [n for n in logged if n in off_plan]
        for slot in by_index[idx]["slots"]:
            if slot["prescribed_sets"] <= 0:
                continue
            key = slot["exercise"].strip().lower()
            if performed.get(key, 0) > 0 or key in logged:
                continue
            want = (db.get(key) or {}).get("primary")
            if not want:
                continue
            for cand in sorted(extras):
                if (d, cand) in claimed:
                    continue
                if (db.get(cand) or {}).get("primary") != want:
                    continue
                claimed.add((d, cand))
                out.append({
                    "prescribed": slot["exercise"].strip(),
                    "performed":  next(
                        (r["exercise"] for r in sessions[d]
                         if (r.get("exercise") or "").strip().lower() == cand),
                        cand),
                    "muscle":     want,
                    "date":       d,
                })
                break
    return out


# ------------------------------------------------------------- D5 bench
BENCH_THRESHOLD = 2      # D5: two unperformed prescriptions and it is benched.
_BENCH_DISPOSITIONS = ("pending", "retired", "retry")


def read_bench_log(person: str) -> dict:
    """The D5 answer store, or an empty one.

    Shape::

        {"version": 1, "entries": [
            {"exercise", "benched_on", "asked_on", "answer",
             "disposition": "pending" | "retired" | "retry"}]}
    """
    from shared.person_paths import bench_log_json
    p = bench_log_json(person)
    if not p.exists():
        return {"version": 1, "entries": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "entries": []}
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return {"version": 1, "entries": []}
    return data


def _bench_index(log: dict) -> dict[str, dict]:
    return {(e.get("exercise") or "").strip().lower(): e
            for e in log.get("entries") or []
            if isinstance(e, dict)}


def record_bench_response(person: str, exercise: str,
                          answer: str | None = None,
                          disposition: str = "pending",
                          on_date: str | None = None) -> dict:
    """Persist the answer to the D5 "why does this never happen" question.

    Idempotent per exercise: an existing entry is updated in place. This
    is what makes "ask once" hold across runs — without a written answer
    the next generation recomputes the same bench list and asks again.

    ``disposition`` routes the exercise:
      * ``retired`` — never prescribe it again (no equipment, disliked,
        contraindicated).
      * ``retry``   — the obstacle was circumstantial; it may return.
      * ``pending`` — asked, not yet answered.
    """
    from shared.person_paths import bench_log_json, ensure_plans_dir
    if disposition not in _BENCH_DISPOSITIONS:
        raise ValueError(f"disposition must be one of {_BENCH_DISPOSITIONS}")
    ensure_plans_dir(person)
    log = read_bench_log(person)
    idx = _bench_index(log)
    key = (exercise or "").strip().lower()
    if not key:
        raise ValueError("exercise is required")
    stamp = on_date or date.today().isoformat()
    entry = idx.get(key)
    if entry is None:
        entry = {"exercise": exercise.strip(), "benched_on": stamp}
        log.setdefault("entries", []).append(entry)
    entry["asked_on"] = entry.get("asked_on") or stamp
    entry["answer"] = answer if answer is not None else entry.get("answer")
    entry["disposition"] = disposition
    log["version"] = 1
    log["entries"].sort(key=lambda e: (e.get("exercise") or "").lower())
    path = bench_log_json(person)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return log


# --------------------------------------------------- the D8 route guard
#
# Benching removes an exercise from the coach's vocabulary. Do it to
# every route into a muscle and the coach is left holding two
# instructions it cannot both obey: "never prescribe these" and "hit
# mid-MAV on calves". It will break one of them, and nothing in the
# system says which.
#
# So a bench is refused when it would take the route pool below the floor
# for that muscle's priority tier. An emphasis or grow muscle needs at
# least two routes — one exercise carrying 10-12 credited sets a week is
# not a program, and `core_week_spec` demands three distinct core
# exercises weekly regardless. Maintenance needs one.
MIN_ROUTES_BY_TIER = {"emphasis": 2, "grow": 2, "maintain": 1}
MIN_ROUTES_DEFAULT = 1
# A core pattern category with no available member cannot contribute to
# `min_pattern_categories_per_week`, so the last one standing is never
# benched — that is precisely where the diversity is being forced.
MIN_ROUTES_PER_CORE_CATEGORY = 1


def _available_routes(catalog: dict | None, rows: list[dict],
                      latest: dict,
                      retired: set[str] | None = None) -> tuple[dict, dict]:
    """Route pools per muscle and per core pattern category.

    A "route" is an exercise the coach can prescribe TODAY with a load it
    can justify: one with logged working-set history, or one in the most
    recent plan. The whole 234-entry catalog is deliberately NOT the pool
    — with 155 never-prescribed entries there would always be another
    route on paper and the guard would never fire, which is exactly the
    failure being prevented.

    ``retired`` removes what the USER has already refused. The pool was
    built from history and the latest plan alone, so an exercise the D5
    flow retired months ago still counted as a live route and kept
    protecting a muscle it can never be prescribed for again — the guard
    then blocked the next bench while the muscle was in fact already
    stranded below its tier floor. Only reachable once the answer flow
    has been used, which is why it survived: neither person has a bench
    log on disk yet.
    """
    by_muscle: dict[str, set[str]] = {}
    by_category: dict[str, set[str]] = {}
    keys: set[str] = set()
    for r in rows:
        if not _is_working_set(r):
            continue
        keys.add((r.get("exercise") or "").strip().lower())
    keys.update(e["name"].strip().lower() for e in latest["per_exercise"])
    keys -= (retired or set())
    for key in keys:
        meta = (catalog or {}).get(key)
        if meta is None or meta.get("is_warmup") or meta.get("is_cardio"):
            continue
        if meta.get("primary"):
            by_muscle.setdefault(meta["primary"], set()).add(key)
        if meta.get("muscle") == "CORE" and meta.get("section"):
            by_category.setdefault(meta["pattern"], set()).add(key)
    return by_muscle, by_category


def _apply_route_guard(candidates: list[dict], catalog: dict | None,
                       db: dict, rows: list[dict], latest: dict,
                       priority_tiers: dict | None,
                       retired: set[str] | None = None) -> tuple[list, list]:
    """Split bench candidates into actually-benched and route-blocked.

    Greedy, strongest evidence first, so the available headroom goes to
    the best-supported benchings and the marginal one is what gets
    refused. A blocked entry is not silently dropped: it comes back as
    ``bench_blocked`` with the muscle it protects, and it takes priority
    in the bench prompt — "you keep skipping this and it is the only
    route to X, do you want a different exercise for that muscle" is a
    far more useful question than a silent retirement.
    """
    by_muscle, by_category = _available_routes(catalog, rows, latest,
                                               retired)
    tiers = priority_tiers or {}
    benched, blocked = [], []
    for cand in candidates:
        key = cand["_key"]
        meta = (catalog or {}).get(key) or {}
        muscle = meta.get("primary")
        category = (meta["pattern"] if meta.get("muscle") == "CORE"
                    and meta.get("section") else None)
        tier = tiers.get(muscle) if muscle else None
        floor = MIN_ROUTES_BY_TIER.get(tier, MIN_ROUTES_DEFAULT)

        # The candidate is unioned into its own pool before counting. It
        # may not be there already — a movement prescribed repeatedly and
        # performed never has no logged history, and it drops out of the
        # pool the moment it also drops out of the newest plan. But the
        # coach WAS using it as that muscle's or category's route, so
        # forbidding it does remove one. Counting only the pool as found
        # let the last anti-rotation movement bench itself precisely
        # because the user had never once done it.
        reason = None
        if muscle:
            remaining = len(by_muscle.get(muscle, set()) | {key}) - 1
            if remaining < floor:
                reason = (
                    f"benching it would leave {remaining} usable route(s) to "
                    f"{muscle}, which is tier '{tier or 'maintain'}' and needs "
                    f"at least {floor}")
        if reason is None and category:
            remaining = len(by_category.get(category, set()) | {key}) - 1
            if remaining < MIN_ROUTES_PER_CORE_CATEGORY:
                reason = (
                    f"it is the last usable movement in core pattern category "
                    f"'{category}', which the weekly pattern requirement needs")

        entry = dict(cand)
        entry["muscle"] = muscle
        entry["core_category"] = category
        entry["priority_tier"] = tier
        if reason:
            entry["blocked_reason"] = reason
            blocked.append(entry)
            continue
        if muscle:
            by_muscle.setdefault(muscle, set()).discard(key)
        if category:
            by_category.setdefault(category, set()).discard(key)
        benched.append(entry)
    return benched, blocked


def _bench_prompt(benched: list[dict], blocked: list[dict]) -> dict | None:
    """The single question the assessment asks, D5.

    A route-blocked exercise outranks a benched one: it is a live
    contradiction the coach cannot resolve on its own, and the answer
    ("swap it for a different <muscle> movement") changes the plan
    immediately.
    """
    unasked_blocked = [b for b in blocked if b["disposition"] == "unasked"]
    unasked_benched = [b for b in benched if b["disposition"] == "unasked"]
    if unasked_blocked:
        top = unasked_blocked[0]
        # Name the thing that would actually be stranded. "the only route
        # to core" is not a useful sentence when the real gap is that
        # anti-rotation work has never once happened.
        what = (f"the only {top['core_category'].split('/')[-1].lower()} "
                f"movement you have" if top.get("core_category")
                else f"one of the few routes you have to {top['muscle']}")
        question = (
            f"{top['exercise']} was prescribed into "
            f"{top['tested_count']} sessions you trained and logged zero "
            f"working sets — but it is {what}, and that is a priority this "
            f"block. Do you want a different exercise for it, or is something "
            f"about this one fixable?")
    elif unasked_benched:
        top = unasked_benched[0]
        question = (
            f"{top['exercise']} has been prescribed into "
            f"{top['tested_count']} sessions you trained and logged zero "
            f"working sets. What stops it — equipment, dislike, or it just "
            f"gets cut for time?")
    else:
        return None
    return {
        "exercise": top["exercise"],
        "kind":     "route_blocked" if unasked_blocked else "benched",
        "question": question,
        "ask_once": True,
        "persist_with": (
            "python3 -m workout_coach.lib.adherence bench-record "
            "--person <Name> --exercise "
            f"\"{top['exercise']}\" --disposition retired|retry "
            "--answer \"<their words>\""),
        "n_awaiting_answer": len(unasked_blocked) + len(unasked_benched),
    }


# ----------------------------------------------------------- the ledger
def build_adherence(person: str, rows: list[dict], db: dict, today_d: date,
                    catalog: dict | None = None,
                    history: int = 8,
                    priority_tiers: dict | None = None) -> dict | None:
    """The ``adherence`` payload block for ``person``.

    Headline numbers describe the MOST RECENT plan's window — that is the
    prescription the next generation is answering. ``consecutive_unperformed``,
    ``benched`` and ``never_performed`` are computed across the last
    ``history`` plans, because a single window cannot tell a movement
    skipped once from one skipped every time it has ever been asked for.

    ``priority_tiers`` is ``constants.muscle_priority_tiers(profile)[0]``.
    It is what stops the bench from contradicting D8 — see
    ``_apply_route_guard``. Omit it and every muscle falls to the
    maintenance floor of one route, which is the permissive reading.

    Three lists come out of this, and they answer three different
    questions:

      ``benched``          the coach must not re-prescribe these.
      ``bench_blocked``    it would, but that would strand a priority
                           muscle or a core pattern category; ask instead.
      ``never_performed``  prescribed into >= 2 trained sessions and
                           performed in none of them. Overlaps ``benched``
                           but is not the same set: a movement performed
                           six months ago and skipped twice since is
                           benched and is NOT "never performed", and the
                           entries carry ``ever_logged`` / ``last_logged``
                           so the distinction is legible.

    Returns ``None`` when the person has no plans on disk (a first run),
    so ``_compact`` drops the key rather than emitting a block of zeroes
    that reads like 0% adherence.
    """
    plans = load_plans(person, today_d, limit=history)
    if not plans:
        return None
    windows = plan_windows(plans, today_d)
    reconciled = [reconcile_plan(p, s, e, rows, db, catalog)
                  for p, s, e in windows]
    latest = reconciled[-1]

    # Only CLOSED windows count toward the bench. The newest window is
    # still open until a plan replaces it, and a window three days old
    # has not had time to be executed — benching off it would retire a
    # movement the day after prescribing it, which is not what D5's "two
    # unperformed prescriptions" means. The open window still appears in
    # every headline number; it just does not accrue evidence yet.
    closed = [r for r in reconciled
              if r is not reconciled[-1]
              or r["window_days"] >= MIN_CLOSED_WINDOW_DAYS]
    latest_window_open = latest["window_days"] < MIN_CLOSED_WINDOW_DAYS

    # Everything the person has ever logged, so a bench reason can say
    # "not performed since it was prescribed" without claiming "never
    # performed" about a movement with a real history behind it.
    ever_logged: dict[str, str] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        k = (r.get("exercise") or "").strip().lower()
        if r.get("date") and r["date"] > ever_logged.get(k, ""):
            ever_logged[k] = r["date"]

    # Per-exercise history across every closed window: the trailing run
    # of TESTED prescriptions with zero performed sets is what D5 keys on.
    #
    # ``history`` gets an entry only when the exercise was prescribed into
    # a workout the user actually performed. A prescription inside a
    # session that never happened is untested — the user did not decline
    # the movement, the session did not occur — and counting it benched
    # eleven exercises at once off two skipped leg days, including every
    # route to two of the five emphasis muscles. ``sessions_missed``
    # carries that fact instead, because a chronically skipped session is
    # real signal, just a different one.
    seen: dict[str, dict] = {}
    for rec in closed:
        for e in rec["per_exercise"]:
            key = e["name"].strip().lower()
            h = seen.setdefault(key, {
                "name": e["name"], "prescribed_count": 0,
                "prescribed_sets": 0, "performed_sets": 0,
                "tested_count": 0, "sessions_missed": 0,
                "history": [], "is_isolation": e["is_isolation"],
            })
            h["prescribed_count"] += 1
            h["prescribed_sets"] += e["prescribed_sets"]
            h["performed_sets"] += e["performed_sets"]
            if e["tested"]:
                h["tested_count"] += 1
                h["history"].append(e["performed_sets"] > 0)
            else:
                h["sessions_missed"] += 1

    def _consecutive_unperformed(flags: list[bool]) -> int:
        n = 0
        for done in reversed(flags):
            if done:
                break
            n += 1
        return n

    # A substitution redeems the prescription it stood in for: the user
    # trained the muscle, so the movement is not being avoided and must
    # not accrue toward the bench.
    substituted: dict[str, int] = {}
    for rec in closed:
        for s in rec["substitutions"]:
            k = s["prescribed"].strip().lower()
            substituted[k] = substituted.get(k, 0) + 1

    latest_names = {e["name"].strip().lower() for e in latest["per_exercise"]}
    per_exercise = []
    for e in latest["per_exercise"]:
        key = e["name"].strip().lower()
        h = seen.get(key) or {"history": [], "sessions_missed": 0,
                              "tested_count": 0, "prescribed_sets": 0,
                              "performed_sets": 0}
        per_exercise.append({
            "name":                   e["name"],
            "prescribed_sets":        e["prescribed_sets"],
            "tested_prescribed_sets": e["tested_prescribed_sets"],
            "performed_sets":         e["performed_sets"],
            "overshoot_sets":         e["overshoot_sets"],
            "completion_rate":        e["completion_rate"],
            "tested_completion_rate": e["tested_completion_rate"],
            "consecutive_unperformed": _consecutive_unperformed(h["history"]),
            # The same ratio across every CLOSED window. The headline
            # rates above describe the newest window, which is open on
            # the generation that writes it — every rate reads 0 that
            # day, and any consumer thresholding on them flips answer
            # depending on whether the plan file happens to exist yet.
            # This one does not move.
            "closed_completion_rate": (
                round(min(h.get("performed_sets") or 0,
                          h.get("prescribed_sets") or 0)
                      / h["prescribed_sets"], 3)
                if h.get("prescribed_sets") else None),
            "prescriptions_tested":   h["tested_count"],
            # Windows where every workout holding this exercise went
            # undone. Not a refusal of the movement — a missed session.
            "sessions_missed":        h["sessions_missed"] or None,
            "is_isolation":           e["is_isolation"],
        })

    bench_log = read_bench_log(person)
    bench_idx = _bench_index(bench_log)

    candidates, never = [], []
    for key, h in sorted(seen.items()):
        consec = _consecutive_unperformed(h["history"])
        subs = substituted.get(key, 0)
        last_log = ever_logged.get(key)
        # "Never performed" means never performed in a window where it was
        # prescribed INTO A SESSION THAT HAPPENED, and it takes at least
        # two such asks before that is a pattern rather than one skip.
        if (h["performed_sets"] == 0 and h["tested_count"] >= BENCH_THRESHOLD
                and subs == 0):
            never.append({
                "exercise":         h["name"],
                "prescribed_count": h["prescribed_count"],
                "tested_count":     h["tested_count"],
                "ever_logged":      bool(last_log),
                "last_logged":      last_log,
            })
        if consec < BENCH_THRESHOLD or subs >= consec:
            continue
        stored = bench_idx.get(key) or {}
        if stored.get("disposition") == "retry":
            continue
        candidates.append({
            "exercise":         h["name"],
            "prescribed_count": h["prescribed_count"],
            "tested_count":     h["tested_count"],
            "sessions_missed":  h["sessions_missed"] or None,
            "reason":           (
                f"{consec} consecutive prescriptions unperformed in sessions "
                f"that were trained"
                if h["performed_sets"] else
                f"prescribed into {h['tested_count']} sessions that were "
                f"trained, performed in none of them"),
            "ever_logged":      bool(last_log),
            "last_logged":      last_log,
            "answer":           stored.get("answer"),
            "disposition":      stored.get("disposition") or "unasked",
            "still_prescribed": key in latest_names,
            "_consec":          consec,
            "_key":             key,
        })
    # Strongest evidence first, so the greedy route guard below spends the
    # available headroom on the best-supported benchings.
    candidates.sort(key=lambda b: (-b["_consec"], -b["prescribed_count"],
                                   b["exercise"]))
    retired = {k for k, e in bench_idx.items()
               if (e.get("disposition") or "") == "retired"}
    benched, blocked = _apply_route_guard(
        candidates, catalog, db, rows, latest, priority_tiers, retired)
    for b in benched + blocked:
        b.pop("_consec", None)
        b.pop("_key", None)

    prompt = _bench_prompt(benched, blocked)

    # Which sessions keep going undone, across every closed window. Keyed
    # on the heading slug, not the workout index: workout 3 of one plan
    # and workout 3 of the next are routinely different sessions.
    closed_ids = {id(r) for r in closed}
    session_stats: dict[str, dict] = {}

    def _session_stat(key, title, stype):
        return session_stats.setdefault(key, {
            "session": key, "title": title, "session_type": stype,
            "planned": 0, "missed": 0,
        })

    for (plan, _s, _e), rec in zip(windows, reconciled):
        if id(rec) not in closed_ids:
            continue
        for w in plan.get("workouts") or []:
            _session_stat(w.get("session") or f"workout_{w['index']}",
                          w.get("title"), w.get("session_type"))["planned"] += 1
        for m in rec["missed_sessions"]:
            _session_stat(m["session"] or f"workout_{m['index']}",
                          m["title"], m["session_type"])["missed"] += 1
    missed_sessions = sorted(
        (s for s in session_stats.values() if s["missed"]),
        key=lambda s: (-s["missed"], s["session"]))

    return {
        "window":             latest["window"],
        "window_days":        latest["window_days"],
        # True while the newest plan is still live: its misses are not yet
        # misses. Say so rather than reporting a partial week as a verdict.
        "window_open":        latest_window_open,
        "plan_date":          latest["plan_date"],
        "plans_reconciled":   len(reconciled),
        "windows_closed":     len(closed),
        "sessions_planned":   latest["sessions_planned"],
        "sessions_performed": latest["sessions_performed"],
        "workouts_never_done": latest["workouts_never_done"],
        "missed_sessions":    missed_sessions or None,
        "sets_prescribed":    latest["sets_prescribed"],
        # Sets prescribed into sessions that were actually trained. The
        # denominator of `tested_completion_rate`; the gap between the two
        # is attendance, not truncation.
        "sets_prescribed_tested": latest["sets_prescribed_tested"],
        "sets_performed":     latest["sets_performed"],
        "sets_credited":      latest["sets_credited"],
        "sets_overshoot":     latest["sets_overshoot"],
        "sets_off_plan":      latest["sets_off_plan"],
        "completion_rate":    latest["completion_rate"],
        "tested_completion_rate": latest["tested_completion_rate"],
        "isolation_completion_rate": latest["isolation_completion_rate"],
        "compound_completion_rate":  latest["compound_completion_rate"],
        "per_exercise":       per_exercise,
        "benched":            benched,
        "bench_blocked":      blocked or None,
        "never_performed":    sorted(never, key=lambda n: (-n["prescribed_count"],
                                                           n["exercise"])),
        "substitutions":      latest["substitutions"],
        "bench_prompt":       prompt,
        "is_deload":          latest["is_deload"],
        "history": [
            {"plan_date": r["plan_date"],
             "sets_prescribed": r["sets_prescribed"],
             "sets_performed": r["sets_performed"],
             "completion_rate": r["completion_rate"],
             # A deload week prescribes half the sets on purpose. Folding
             # it into the trend without the flag makes a recovery week
             # read as a compliance problem.
             "is_deload": r["is_deload"] or None}
            for r in reconciled
        ],
        "parse_errors": [e for p in plans for e in p["parse_errors"]] or None,
        # Bullets that were read and are worth zero working sets. Not
        # errors; surfaced so "the plan has ten bullets and the ledger
        # counted eight" is answerable without re-reading the markdown.
        "parse_notes": [n for p in plans
                        for n in p.get("parse_notes") or []] or None,
    }


# ------------------------------------------------------- dose staleness
# What counts as the dose actually moving. Both floors exist because the
# cheapest way to satisfy "the dose must change" is to change it by an
# amount no muscle can detect: 90 kg to 90.5 kg, or a rep range widened
# from 8-10 to 8-11 while the midpoint barely shifts. Anything under
# these floors is reported as ``cosmetic`` and counted as UNCHANGED.
DOSE_LOAD_MIN_PCT = 0.02      # 2% — inside plate/stack granularity below this.
DOSE_REP_MIN_MIDPOINT = 1.0   # one whole rep of midpoint movement.


def _rep_midpoint(slot: dict) -> float | None:
    lo, hi = slot.get("rep_lo"), slot.get("rep_hi")
    if lo is None and hi is None:
        return None
    if lo is None:
        return float(hi)
    if hi is None:
        return float(lo)
    return (float(lo) + float(hi)) / 2.0


def _dose_delta(prev: dict, cur: dict) -> tuple[str, bool]:
    """Classify the change between two prescriptions of one exercise."""
    pl, cl = prev.get("load_kg"), cur.get("load_kg")
    if pl is not None and cl is not None and pl > 0:
        rel = (cl - pl) / pl
        if abs(rel) >= DOSE_LOAD_MIN_PCT:
            return ("load_up" if rel > 0 else "load_down", True)
    elif (pl is None) != (cl is None):
        return ("load_added" if cl is not None else "load_removed", True)
    pm, cm = _rep_midpoint(prev), _rep_midpoint(cur)
    if pm is not None and cm is not None:
        if abs(cm - pm) >= DOSE_REP_MIN_MIDPOINT:
            return ("reps_up" if cm > pm else "reps_down", True)
    ps, cs = prev.get("prescribed_sets"), cur.get("prescribed_sets")
    if ps != cs:
        return ("sets_up" if (cs or 0) > (ps or 0) else "sets_down", True)
    if (pl, pm) != (cl, cm):
        return ("cosmetic", False)
    return ("none", False)


def dose_staleness(plans: list[dict], db: dict | None = None) -> dict | None:
    """Per carried-forward exercise: did its dose move, and for how long not.

    "Carried forward" means the exercise appears in the newest plan AND
    in the one before it. 70% of those returned with an unchanged load;
    the target is under 40%. This block is what lets a validator check
    that, and what lets the coach see which specific lifts it has been
    re-copying.

    ``oscillating`` is the second-order guard: a coach that satisfies
    "the dose must change" by alternating 90 / 92.5 / 90 / 92.5 has
    changed the dose on every generation and progressed nothing.
    """
    if len(plans) < 2:
        return None
    # Per plan, the best (heaviest / most-set) prescription of each
    # exercise. A movement prescribed in two workouts of the same plan
    # gets one dose, otherwise the comparison is between arbitrary halves.
    series: dict[str, list[tuple[str, dict]]] = {}
    for plan in plans:
        best: dict[str, dict] = {}
        for w in plan.get("workouts") or []:
            for s in w["slots"]:
                if s["prescribed_sets"] <= 0:
                    continue
                key = s["exercise"].strip().lower()
                # Warmups carry no dose to progress. "Jumping Jacks: 50"
                # unchanged for eight generations is not dose staleness,
                # and leaving them in pads the denominator with rows that
                # can only ever read as unchanged.
                cat = (db or {}).get(key) or {}
                if cat.get("is_warmup") or cat.get("is_cardio"):
                    continue
                cur = best.get(key)
                if cur is None or (s.get("load_kg") or 0) > (cur.get("load_kg") or 0):
                    best[key] = s
        for key, slot in best.items():
            series.setdefault(key, []).append((plan["plan_date"], slot))

    latest_date = plans[-1]["plan_date"]
    prev_date = plans[-2]["plan_date"]
    carried = []
    for key, hist in sorted(series.items()):
        dates = [d for d, _ in hist]
        if latest_date not in dates or prev_date not in dates:
            continue
        slots = [s for _, s in hist]
        kind, changed = _dose_delta(slots[-2], slots[-1])
        static = 0
        for i in range(len(slots) - 1, 0, -1):
            _, moved = _dose_delta(slots[i - 1], slots[i])
            if moved:
                break
            static += 1
        loads = [s.get("load_kg") for s in slots[-4:]]
        oscillating = (len(loads) == 4 and len(set(loads)) == 2
                       and loads[0] == loads[2] and loads[1] == loads[3])
        carried.append({
            "exercise":            slots[-1]["exercise"],
            "load_kg":             slots[-1].get("load_kg"),
            "prev_load_kg":        slots[-2].get("load_kg"),
            "rep_target":          slots[-1].get("rep_target"),
            "prev_rep_target":     slots[-2].get("rep_target"),
            "dose_changed":        changed,
            "change_kind":         kind,
            "generations_static":  static,
            "generations_seen":    len(slots),
            "oscillating":         oscillating,
        })
    if not carried:
        return None
    unchanged = [c for c in carried if not c["dose_changed"]]
    # Two denominators, deliberately. The measured 70% baseline counted
    # LOAD only; this module counts a rep-target move as a real dose
    # change, which it is — the 2026-07-25 plan progressed several lifts
    # by opening the rep range instead of adding weight, and calling that
    # "unchanged" is wrong. But redefining the metric is also how a
    # target gets hit without anything improving, so the load-only figure
    # is reported beside it and stays comparable to the baseline. It is
    # the number that catches "widen the rep range forever, never touch
    # the weight".
    loaded = [c for c in carried if c["load_kg"] is not None
              and c["prev_load_kg"] is not None]
    unchanged_load = [c for c in loaded
                      if c["change_kind"] not in ("load_up", "load_down")]
    return {
        "from_plan":       prev_date,
        "to_plan":         latest_date,
        "carried_count":   len(carried),
        "unchanged_count": len(unchanged),
        "unchanged_pct":   round(len(unchanged) / len(carried), 3),
        "target_max_pct":  0.40,
        "meets_target":    len(unchanged) / len(carried) < 0.40,
        "loaded_count":       len(loaded),
        "unchanged_load_pct": (round(len(unchanged_load) / len(loaded), 3)
                               if loaded else None),
        "oscillating_count": sum(1 for c in carried if c["oscillating"]),
        "carried":         sorted(carried,
                                  key=lambda c: (-c["generations_static"],
                                                 c["exercise"])),
    }


# ------------------------------------------------------------------ CLI
def _cli(argv: list[str] | None = None) -> int:
    """Read and write the D5 bench log.

    A lib module with a CLI is the same arrangement
    ``shared/exercises_database.py`` uses, and for the same reason: the
    write is agent-driven and belongs next to the read that defines the
    file's shape, not in a script that would have to restate it.
    """
    import argparse
    import sys
    ap = argparse.ArgumentParser(description="Benched-exercise response log (D5).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("bench-list", help="print the stored responses")
    p_list.add_argument("--person", required=True)
    p_rec = sub.add_parser("bench-record", help="store an answer for one exercise")
    p_rec.add_argument("--person", required=True)
    p_rec.add_argument("--exercise", required=True)
    p_rec.add_argument("--answer", default=None)
    p_rec.add_argument("--disposition", default="pending",
                       choices=list(_BENCH_DISPOSITIONS))
    p_rec.add_argument("--date", dest="on_date", default=None)
    args = ap.parse_args(argv)

    if args.cmd == "bench-list":
        json.dump(read_bench_log(args.person), sys.stdout,
                  ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0
    log = record_bench_response(args.person, args.exercise, args.answer,
                                args.disposition, args.on_date)
    json.dump(log, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(_cli())
