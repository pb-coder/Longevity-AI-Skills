"""Double progression: the next prescription for each lift, from the log.

``next_dose`` is the one place a load or a rep target is decided. The coach
copies it; it does not pick weights itself. Until this existed the rule
lived in SKILL.md prose ("if the user hit the top of the rep range, bump
weight, but only above recovery 6.5 and TSB +5"), the prose gated the bump
behind thresholds the code never used, and the fallback under "hold" was to
widen the rep range with no ceiling. A lift sat at one weight for fifteen
sessions while its range climbed from 8-10 to 12-14.

The rule, per exercise, off the last session worked:

* Take the rep range the plan in force prescribed. If its top is above the
  ceiling (compounds 12, isolation 20) the range is reset to the ceiling
  range: more reps than that is endurance, the lift is owed weight.
* At least two working sets at the top load, every one of them at the top of
  the range: add the lift's increment and start the range again from its
  bottom. This rule is the readiness check: a lift that has not earned weight
  does not get it, and one that has is not held back by a middling recovery
  score. A single working set never earns it.
* Otherwise: same load, same range, more reps.
* A load the lifter could not do is re-derived from the last session's best
  set by the Epley inverse at the bottom of the range, rounded to the NEAREST
  step of the lift's grid. It is never raised, and a shortfall under half a
  step lands on the last load, which is then kept (the stall rule takes it
  from there). That happens in two cases only: a re-entry
  after a break, or a best set that missed the bottom of the range in each of
  the last TWO sessions at that same load. One bad session keeps the load
  (action ``add_reps``) and the basis says the next miss at it drops it.
* A re-entry always has a range: when no plan or block ever prescribed one it
  is the first range on `REP_RANGE_LADDER` whose top holds the median reps of
  the last session, capped at the class ceiling (compounds 12, isolation 20),
  and ``range_from`` says so. Past `blocks.ROTATION_CANDIDATE_WINDOW_DAYS` (56)
  away, the re-derived load also takes `blocks.NOVELTY_DISCOUNT`, the same
  first-exposure discount ``rotation_candidates`` applies, and a re-entry load
  is rounded to the NEAREST step, as ``rotation_candidates`` does. The two use
  the same e1RM, discount and rounding but NOT the same rep count: a re-entry
  here is priced at the bottom of its own range, a ``rotation_candidates``
  entry at its ``target_reps``, so they can differ for one lift. ``next_dose``
  is the one to copy (SKILL.md, Loads and reps).
* How long ago a lift was worked decides whether it is a re-entry, and that
  is its most recent session of any kind (another gym and a marked deload
  included: the movement was practised). The load it comes back at is still
  the usual gym's, non-deload reference session.
* A prescribed top of one or two reps (``1``, ``2``, ``1-2``) is a heavy
  single or double judged by effort, not by counting reps: two sets "at the
  top" prove nothing about whether another kilo is safe. It is never bumped
  automatically (`NEXT_DOSE_MIN_TOP_REPS`): ``hold``, same load, and the basis
  says so.
* A single-number prescription (``12``) is a target, the top of the range,
  not a range with no room: it is read as ``n-2`` up to ``n`` (``10-12``,
  ``6-8`` for an 8, ``3-5`` for a 5), so a set one or two reps under the
  target is not "below the range".
* The gate's ``load_policy`` can turn the whole thing into a deload
  (``reduce``, on a red-flag day only). It never invents a bump.
* The increment is the most common positive jump in the person's own log for
  that lift, used as it stands (a 2 kg step on a two-dumbbell lift is 1 kg a
  hand and real); the equipment table is only the fallback when the log has
  no usable majority (`observed_increment`), from the whole
  `INCREMENT_HISTORY_MONTHS` of the log. For a machine, cable, Smith or
  landmine lift, whose load depends on the gym, only the stretch at the
  CURRENT gym counts: jumps before the person's most recent gym/machine-change
  note on any lift of that session day were learned on other equipment (a
  barbell, dumbbell or plate lift weighs the same everywhere and is never cut
  there). A jump no bigger than the smallest real step of the lift
  (`constants.smallest_real_step_kg`: 2 kg for two dumbbells, 1 kg for one,
  1 kg otherwise) AND under 5% of the load it started from is re-weighing
  noise (`constants.is_reweigh_jump`) and is not counted: 55 -> 56 kg is,
  4 -> 5 kg on a cable is a step.
* A lift prescribed in two workouts with two doses (a heavy 6-8 and a light
  12-15) is judged against the dose of the workout its last session matched
  (`adherence.session_workout_candidates`), not against whichever slot has the
  most sets. With no match the largest dose stands and ``range_from`` says so.
* A machine, cable, Smith or landmine lift is judged on the usual gym: its
  load comes from the most recent sessions NOT flagged as a different gym,
  and the most recent load at the flagged gym rides beside it as
  ``other_gym_load_kg``.

Every entry names what it was based on, and an exercise with nothing logged
says so rather than receiving a number: ``blocks.rotation_candidates``
owns cold-start loads. Every exercise worked inside the history window gets
an entry (a lapsed one as a ``hold`` re-entry), except the movements the
person has retired.
"""
from __future__ import annotations

import statistics
from datetime import date, timedelta

from .adherence import plan_doses, session_workout_candidates
from .blocks import NOVELTY_DISCOUNT, ROTATION_CANDIDATE_WINDOW_DAYS
from .constants import (
    MAX_PLAUSIBLE_JUMP_FRACTION,
    MAX_PLAUSIBLE_JUMP_STEPS,
    MIN_OBSERVED_JUMPS,
    NOISE_JUMP_FRACTION,
    REP_CEILING_RANGE,
    STALE_EXERCISE_DAYS,
    equipment_increment_kg,
    is_reweigh_jump,
)
from .parsing import _parse_iso_date
from .strength import (
    GYM_INVARIANT_EQUIPMENT,
    context_change_days,
    epley_e1rm,
    exercise_class,
    load_for_reps,
    load_stall_sessions,
    loads_equal,
    session_history,
)

# How many months of the log the increment is learned from, wider than the
# reference window: a lift that steps once a month shows two jumps in a quarter
# at best, and its step is a fact about the gym's equipment, not about the
# last session. `read_tracker` reads this many months for the jump rows.
INCREMENT_HISTORY_MONTHS = 6

# How far back a reference session may be drawn from, and so which lifts get
# an entry at all: everything worked inside this window. Beyond this the
# person is not the person the number describes. (`read_tracker` loads three
# months of rows, so the window the data really covers is the shorter of the
# two.)
NEXT_DOSE_HISTORY_DAYS = 120

# "Every working set hit the top" needs more than one set to mean anything:
# one heavy set among lighter back-offs is a top set, not a double
# progression, and a session of one set proves nothing. A bump needs at least
# this many working sets at the load.
NEXT_DOSE_MIN_SETS_AT_LOAD = 2

# A prescription whose top is below this many reps (a single, a double) is
# never bumped on the strength of the log alone: see the module docstring.
NEXT_DOSE_MIN_TOP_REPS = 3

# The standard rep ranges, narrow to wide. A re-entry with no range on record
# takes the first one whose top holds the median reps of its last session:
# the range the lift was really done in, not the class ceiling (a lift worked
# at 10 reps is not owed a 15-20 range and the lighter load that comes with it).
REP_RANGE_LADDER = ((6, 8), (8, 10), (10, 12), (12, 15), (15, 20))

UNCOVERED_REASON = ("no external load to add, a timed hold or carry, or not "
                    "in the exercise catalog: no dose is derived, progress "
                    "by reps or seconds as before")


def _range_str(lo: int, hi: int) -> str:
    return str(lo) if lo == hi else f"{lo}-{hi}"


def _fit_distance(slot: dict, session: dict) -> tuple:
    """How far ``session`` is from ``slot``'s dose: (load gap in kg, reps
    outside the range), smaller is closer. Only used to break a tie between
    workouts that prescribe the same lift."""
    load, reps = _working_load(session)
    gap = abs((slot.get("load_kg") or load) - load)
    med = statistics.median(reps)
    out = max(slot["rep_lo"] - med, med - slot["rep_hi"], 0)
    return round(gap, 2), out


def _slot_for_session(key: str, plan: dict, doses: dict, per_workout: dict,
                      session: "dict | None", rows: "list[dict] | None",
                      catalog: "dict | None") -> tuple:
    """``(slot, how)``: the dose of ``plan`` that governed ``session`` (one
    lift's record of one date), and ``how`` (``None`` when there was only
    one dose).

    ``doses`` is the plan's one-dose-per-lift view (`adherence.plan_doses`,
    the slot with the most sets). That is right while a lift has one dose in
    the plan. When the plan gives it different rep ranges in different
    workouts (a heavy 6-8 and a light 12-15) the session is judged against
    the dose of the workout it was credited to, the way the adherence ledger
    credits it (`adherence.session_workout_candidates`). Workouts that tie
    on coverage (the lift is all the session did, or all it shares with
    both) are told apart by which dose the logged load and reps are closest
    to. A session that matched no workout holding the lift falls back to the
    largest dose and says so.
    """
    slot = doses.get(key)
    held = {i: w[key] for i, w in per_workout.items()
            if key in w and w[key].get("rep_lo") is not None
            and w[key].get("rep_hi") is not None}
    if len({(x["rep_lo"], x["rep_hi"]) for x in held.values()}) < 2 \
            or session is None:
        return slot, None
    cands = [i for i in session_workout_candidates(
        plan, rows or [], session["date"], catalog or {}) if i in held]
    if cands:
        idx = min(cands, key=lambda i: (_fit_distance(held[i], session), i))
        title = next((w["title"] for w in plan["workouts"]
                      if w["index"] == idx), "")
        return held[idx], f"workout {idx}: {title}".rstrip(": ")
    return slot, "the session matched no workout that holds it: the largest dose"


def _prescribed_range(key: str, last_date: str, plan_slots: list[tuple],
                      block_slots: dict, session: "dict | None" = None,
                      rows: "list[dict] | None" = None,
                      catalog: "dict | None" = None) -> tuple:
    """``(lo, hi, source)`` for ``key``, or ``(None, None, None)``.

    The range that governed the LAST SESSION is what that session is judged
    against: the newest plan dated on or before it that prescribes the lift,
    and within that plan the dose of the workout the session matched when
    the plan gives the lift more than one (`_slot_for_session`; ``session``
    is the lift's record of ``last_date``, ``rows`` and ``catalog`` are what
    the match needs). A plan written after the session
    is a guess about the next one and says nothing about whether this one
    earned a bump. Then the block's recorded dose, then (last resort) the
    oldest plan written after the session.

    ``plan_slots`` is ``[(plan_date, doses, plan, per_workout_doses)]``,
    oldest first.
    """
    for plan_date, doses, plan, per_workout in reversed(plan_slots):
        if plan_date > last_date:
            continue
        slot, how = _slot_for_session(key, plan, doses, per_workout,
                                      session, rows, catalog)
        if slot and slot.get("rep_lo") is not None \
                and slot.get("rep_hi") is not None:
            return (slot["rep_lo"], slot["rep_hi"],
                    f"plan {plan_date}" + (f", {how}" if how else ""))
    dose = block_slots.get(key) or {}
    if dose.get("rep_lo") is not None and dose.get("rep_hi") is not None:
        return dose["rep_lo"], dose["rep_hi"], "block"
    for plan_date, doses, _plan, _pw in plan_slots:
        if plan_date <= last_date:
            continue
        slot = doses.get(key)
        if slot and slot.get("rep_lo") is not None \
                and slot.get("rep_hi") is not None:
            return (slot["rep_lo"], slot["rep_hi"],
                    f"plan {plan_date}, written after the last session")
    return None, None, None


def _normalise_range(lo, hi, cls: str | None) -> tuple:
    """``(lo, hi, note)``: the prescribed range, capped at the class ceiling."""
    if lo is None or hi is None:
        return None, None, None
    lo, hi = min(lo, hi), max(lo, hi)
    ceiling = REP_CEILING_RANGE.get(cls)
    if ceiling and hi > ceiling[1]:
        return (ceiling[0], ceiling[1],
                f"prescribed {_range_str(lo, hi)} is above the {cls} ceiling "
                f"of {ceiling[1]} reps, so the range is "
                f"{_range_str(*ceiling)}")
    if lo == hi and hi > 1:
        # A bare "12" is the top the lifter is aiming at. Read as a range
        # whose bottom is also 12, any set under 12 "missed the bottom".
        return (max(1, hi - 2), hi,
                f"prescribed {hi} is a single number, read as the top of "
                f"{_range_str(max(1, hi - 2), hi)}")
    return lo, hi, None


def _ladder_range(median_reps: float, cls: str) -> tuple:
    """The first `REP_RANGE_LADDER` range whose top is at least ``median_reps``,
    or the class ceiling range when that top would be above the ceiling."""
    ceiling = REP_CEILING_RANGE[cls]
    for lo, hi in REP_RANGE_LADDER:
        if hi >= median_reps:
            return (lo, hi) if hi <= ceiling[1] else ceiling
    return ceiling


def _working_load(rec: dict) -> tuple:
    """``(load, reps)``: the heaviest load a session really worked at.

    A heavier top set among lighter ones is a top set, not the load the
    session was built on, and judging "every set hit the top" on one set
    would hand out a bump the other sets never earned. So the reference is
    the heaviest load that carries at least `NEXT_DOSE_MIN_SETS_AT_LOAD`
    sets (or every set, in a shorter session). If no load does, the
    heaviest one is used and the caller sees the shortfall in ``len(reps)``.
    """
    pairs = [(kg, reps) for kg, reps in zip(rec["loads"], rec["reps"])
             if kg > 0]
    need = min(NEXT_DOSE_MIN_SETS_AT_LOAD, rec["sets"])
    groups = []
    for kg in sorted({kg for kg, _ in pairs}, reverse=True):
        groups.append((kg, [r for k, r in pairs if loads_equal(k, kg)]))
    for kg, reps in groups:
        if len(reps) >= need:
            return kg, reps
    return groups[0]


def _missed_bottom_at(session: dict, load: float, lo: "int | None") -> bool:
    """Whether ``session`` was worked at ``load`` and its best set at that
    load stayed under ``lo``, the bottom of the range it was judged against."""
    if lo is None or not session["top_load_kg"]:
        return False
    s_load, s_reps = _working_load(session)
    return loads_equal(s_load, load) and max(s_reps) < lo


def _sessions_at_load(sessions: list[dict]) -> int:
    run = 0
    for s in reversed(sessions):
        if not loads_equal(s["top_load_kg"], sessions[-1]["top_load_kg"]):
            break
        run += 1
    return run


def observed_increment(sessions: list[dict], fallback: float,
                       since: "str | None" = None,
                       is_noise: "callable | None" = None) -> tuple:
    """``(increment_kg, basis)``: what this person's own log says one step is.

    ``sessions`` is one lift's `session_history`, oldest first. The jumps are
    the positive changes in working load between consecutive comparable
    sessions: a gym/machine-flagged session is left out because its load
    says nothing about the step the person takes here, and the caller has
    already dropped the deloads. A jump larger than
    `MAX_PLAUSIBLE_JUMP_FRACTION` of the load it started from AND larger than
    `MAX_PLAUSIBLE_JUMP_STEPS` fallback steps is a gap in the log or a change
    of convention, not a step.

    ``since`` (an ISO date) leaves out every session before it: a jump needs
    both its sessions on or after that date, because the sessions before it
    were at another gym (`build_next_dose` sets it from the latest
    gym-change note, for a lift whose load depends on the gym; ``None``
    otherwise: the whole history counts). ``is_noise(jump, start)`` says
    whether a jump is the same load logged a little differently (64 <-> 65 kg
    of dumbbells), not a step (`constants.is_reweigh_jump`); such a jump is
    not counted. The table is not raised to the smallest step either: a
    learned step finer than the table's (1 kg on a cable) stands.

    The increment is the most common jump (the smaller on a tie), provided it
    has been seen at least `MIN_OBSERVED_JUMPS` times, and it is used as it
    stands: light dumbbells really do come in 1 kg-a-hand steps, so a logged
    2 kg step on a two-dumbbell lift is a step and not noise. Otherwise
    ``fallback`` (the equipment table) stands and ``basis`` says why: too few
    jumps, or jumps that are all different sizes, in which case there is no
    most common one and the smallest would be noise.
    """
    loads = []
    for s in sessions:
        if s["context_change"] or not s["top_load_kg"]:
            continue
        if since is not None and s["date"] < since:
            continue
        load, reps = _working_load(s)
        if min(reps) > 0:
            loads.append(load)
    counts: dict[float, int] = {}
    noise = 0
    for prev, cur in zip(loads, loads[1:]):
        jump = round(cur - prev, 2)
        if jump <= 0 or loads_equal(prev, cur):
            continue
        if jump > max(MAX_PLAUSIBLE_JUMP_FRACTION * prev,
                      MAX_PLAUSIBLE_JUMP_STEPS * fallback):
            continue
        if is_noise is not None and is_noise(jump, prev):
            noise += 1
            continue
        counts[jump] = counts.get(jump, 0) + 1
    seen = sum(counts.values())
    window = f" since {since}" if since else ""
    ignored = (f"; {noise} jump{'s' if noise != 1 else ''} ignored as "
               f"re-weighing (no bigger than the smallest real step and "
               f"under {NOISE_JUMP_FRACTION:.0%} of the load)"
               if noise else "")
    if seen < MIN_OBSERVED_JUMPS:
        return fallback, (f"equipment table: {seen} usable load "
                          f"jump{'s' if seen != 1 else ''} in the log"
                          f"{window}, {MIN_OBSERVED_JUMPS} needed{ignored}")
    step = min(counts, key=lambda j: (-counts[j], j))
    if counts[step] < MIN_OBSERVED_JUMPS:
        return fallback, (f"equipment table: the log's {seen} load jumps"
                          f"{window} are all different sizes, so none is "
                          f"the usual step{ignored}")
    return step, (f"log: {step:g}kg in {counts[step]} of {seen} load "
                  f"jumps{window}{ignored}")


def rep_matched_load(session: dict, target_reps: int, load: float,
                     inc: float, discount: float = 1.0) -> tuple:
    """``(load_kg, e1rm, raw_kg)``: the load the lifter can do for ``target_reps``.

    From the session's BEST set (highest Epley e1RM over every loaded set),
    inverted at ``target_reps`` (`strength.load_for_reps`) and multiplied by
    ``discount`` (1.0 unless the caller owes a first-exposure discount; ``raw_kg``
    includes it), then rounded onto the grid of the load the lifter
    actually logged, ``load - k * inc``: a gym whose stack reads 36.25 does not
    have a 35 to set. To the NEAREST step (a shortfall under half a step is
    the last load again, not a whole step off). Never raised above ``load``,
    and never below one step.
    """
    best = max(epley_e1rm(kg, r)
               for kg, r in zip(session["loads"], session["reps"])
               if kg > 0 and r > 0)
    raw = load_for_reps(best, target_reps) * discount
    if raw >= load - 1e-9:
        return load, best, raw
    steps = int((load - raw) / inc + 0.5)             # half a step rounds down
    return max(round(load - steps * inc, 2), inc), best, raw


def _last_prescription(key: str, plans: list[dict], today_s: str):
    """The most recent plan's written dose string for ``key``, or ``None``.

    The ``raw`` text of the bullet as the plan wrote it (``"22-25 /// 22-25"``,
    ``"45s per side /// 45s per side"``), so a timed hold or an unloaded
    movement the dose rule does not cover can still be carried forward. In the
    newest plan that holds it; where it appears in several workouts, the one
    carrying the most sets. A plan dated today or later is not a prescription
    yet (it is this block's own output).
    """
    for plan in reversed(plans):
        if plan["plan_date"] >= today_s:
            continue
        best = None
        for w in plan.get("workouts") or []:
            for slot in w.get("slots") or []:
                if (slot.get("exercise") or "").strip().lower() != key:
                    continue
                if best is None or (slot.get("prescribed_sets") or 0) \
                        > (best.get("prescribed_sets") or 0):
                    best = slot
        if best is not None:
            return best.get("raw") or None
    return None


def build_next_dose(rows: list[dict], catalog: dict, plans: list[dict],
                    block: dict | None, load_policy: dict,
                    today_d: date,
                    deload_dates: "list[str] | None" = None,
                    jump_rows: "list[dict] | None" = None,
                    retired: "set[str] | None" = None) -> dict:
    """The ``next_dose`` payload block.

    ``rows``         the monthly ledger rows, clipped to ``today_d``.
    ``catalog``      `blocks.load_pattern_catalog`: equipment, compound or
                     isolation, warmup/cardio flags.
    ``plans``        `adherence.load_plans`, oldest first. A plan dated
                     ``today_d`` or later is ignored: today's plan, when it
                     is already on disk, is this block's own output.
    ``block``        the payload's ``block``; its slots add exercises that
                     have no history and supply a range of last resort.
    ``load_policy``  ``session_recommendation.load_policy`` from the gate;
                     its ``reason`` is stated once there, not on every entry.
    ``deload_dates`` user-marked deloads. A deload session says nothing
                     about whether the load was earned, so it is not the
                     reference.
    ``jump_rows``    the same ledger over `INCREMENT_HISTORY_MONTHS`, which
                     the increment is learned from; ``rows`` when omitted.
    ``retired``      lower-cased names of movements the person has retired
                     (D5 bench log, disposition ``retired``): no entry, and
                     not listed under ``uncovered`` either.

    ``{"load_policy", "exercises": [entry, ...], "uncovered"}``. An entry:
    ``exercise``, ``load_kg``, ``rep_range``, ``action``
    (``add_load`` / ``add_reps`` / ``hold`` / ``reduce`` / ``no_history``),
    ``basis`` and, where there is a last session, ``last``, ``last_load_kg``
    and ``last_reps`` (the load and the reps per set of that session, as
    numbers), ``sessions_at_load``, ``stalled_sessions``, ``range_from``,
    ``increment_kg`` (the step this lift takes) and ``increment_basis``.
    ``hold`` is per exercise, never from the policy: a re-entry after
    `STALE_EXERCISE_DAYS` or more since its latest session of any kind (its
    load re-derived from the best set, with the class's default range when
    none is on record), every session tagged as another gym, no rep range on
    record, or a prescription that tops out at 1-2 reps. ``other_gym_load_kg`` is the most recent load at the
    flagged gym when it differs from ``load_kg`` (see the module docstring).

    ``uncovered`` is ``{"reason", "exercises": [{"exercise",
    "last_prescription"}]}``: the timed, unloaded or off-catalog work no dose
    is derived for, each with the dose string of the newest plan that
    prescribed it (``None`` when it never was).
    """
    policy = load_policy.get("policy", "progress")
    deload_set = set(deload_dates or [])
    retired_set = {(n or "").strip().lower() for n in (retired or ())}
    retired_set.discard("")
    today_s = today_d.isoformat()
    since = today_d - timedelta(days=NEXT_DOSE_HISTORY_DAYS)
    history = session_history(rows, catalog, since=since, until=today_d)
    jump_source = rows if jump_rows is None else jump_rows
    jump_history = session_history(jump_source, catalog, until=today_d)
    # Where the load step is learned from. A lift whose load depends on the
    # gym (machine, cable, Smith, landmine; `strength.GYM_INVARIANT_EQUIPMENT`)
    # learns only from sessions on or after the latest gym/machine-change
    # note, of ANY lift (the note describes the whole session day): earlier
    # ones were at another gym, and the old gym's sessions are not tagged
    # when the person moves. A barbell, dumbbell or plate lift weighs what it
    # weighs everywhere, so a gym move cannot corrupt its step and it learns
    # from the whole history. No further age limit: the note is what marks a
    # change of equipment, and a limit would throw away the monthly jumps of
    # a slowly progressing lift (`INCREMENT_HISTORY_MONTHS`).
    gym_since = max((d for d in context_change_days(jump_source)
                     if d <= today_s), default=None)

    plan_slots = [(p["plan_date"], plan_doses(p, catalog), p,
                   {w["index"]: plan_doses({"workouts": [w]}, catalog)
                    for w in p.get("workouts") or []})
                  for p in plans if p["plan_date"] < today_s]
    block_slots: dict[str, dict] = {}
    block_names: dict[str, str] = {}
    for s in (block or {}).get("slots") or []:
        k = (s.get("exercise") or "").strip().lower()
        if k:
            block_slots[k] = s.get("dose") or {}
            block_names[k] = s["exercise"].strip()

    # Every lift worked inside the history window, plus the block's slots. A
    # lapsed lift is a re-entry with a load to come back to, not a gap the
    # coach has to fill by guessing.
    keys = (set(history) | set(block_slots)) - retired_set

    entries: list[dict] = []
    uncovered: list[dict] = []
    for key in sorted(keys):
        meta = catalog.get(key) or {}
        if meta.get("is_warmup") or meta.get("is_cardio"):
            continue
        full = history.get(key) or []
        sessions = [s for s in full if s["date"] not in deload_set]
        name = (sessions[-1]["exercise"] if sessions
                else full[-1]["exercise"] if full
                else meta.get("name") or block_names.get(key) or key)
        cls = exercise_class(name, catalog)

        if not sessions:
            # A range of last resort for a lift with no history: the newest
            # plan that prescribed it, else the block's recorded dose.
            blo, bhi, _ = _prescribed_range(key, today_s, plan_slots,
                                            block_slots)
            lo, hi, _ = _normalise_range(blo, bhi, cls)
            if full:
                why = (f"every session of this lift in the last "
                       f"{NEXT_DOSE_HISTORY_DAYS} days was a marked deload, "
                       f"so there is no working load to progress")
            else:
                why = (f"no working set logged in the last "
                       f"{NEXT_DOSE_HISTORY_DAYS} days, so there is no "
                       f"load to progress")
            entries.append({
                "exercise":   name,
                "load_kg":    None,
                "rep_range":  _range_str(lo, hi) if lo is not None else None,
                "action":     "no_history",
                "basis": (f"{why}. Use rotation_candidates[].load_kg if "
                          f"listed, else a load you can control for the "
                          f"range with 2-3 reps in reserve"),
            })
            continue

        # The usual gym: the sessions not tagged as a different gym or
        # machine. Only a gym-dependent lift (machine, cable, Smith, landmine)
        # is ever tagged (`strength.is_context_change`), so this is every
        # session for a free weight. The tagged ones are the other gym.
        usual = [s for s in sessions if not s["context_change"]]
        other = next((s for s in reversed(sessions)
                      if s["context_change"] and s["top_load_kg"]), None)
        last = usual[-1] if usual else sessions[-1]
        if cls is None or last["top_load_kg"] is None:
            uncovered.append({
                "exercise": name,
                "last_prescription": _last_prescription(key, plans, today_s)})
            continue
        load, reps = _working_load(last)
        if min(reps) <= 0:
            uncovered.append({
                "exercise": name,
                "last_prescription": _last_prescription(key, plans, today_s)})
            continue

        plo, phi, source = _prescribed_range(
            key, last["date"], plan_slots, block_slots, last, rows, catalog)
        lo, hi, note = _normalise_range(plo, phi, cls)
        range_s = _range_str(lo, hi) if lo is not None else None
        if note and lo != hi and plo == phi == hi:
            source = f"{source}; bare {hi} read as {range_s}"
        inc, inc_basis = observed_increment(
            [x for x in jump_history.get(key, [])
             if x["date"] not in deload_set],
            equipment_increment_kg(meta.get("equipment"), key),
            since=(None if meta.get("equipment") in GYM_INVARIANT_EQUIPMENT
                   else gym_since),
            is_noise=lambda jump, start, _e=meta.get("equipment"), _k=key:
                is_reweigh_jump(jump, start, _e, _k))
        done = f"{'/'.join(str(r) for r in reps)} reps at {load:g}kg"
        sets_ok = len(reps) >= NEXT_DOSE_MIN_SETS_AT_LOAD
        top_hit = hi is not None and min(reps) >= hi
        earned = top_hit and sets_ok
        # Recency is the lift's latest session of ANY kind, the other gym
        # and a marked deload included: a lift done last week at the other
        # gym, or in a deload, is not a re-entry (the movement was
        # practised). The load and reps above stay the usual gym's, non-
        # deload reference.
        days_since = (today_d - _parse_iso_date(full[-1]["date"])).days
        # When the lift's latest session is not the one the load comes from,
        # the basis says which is which, and what the newer one was.
        newer = full[-1]
        newer_s = None
        if newer is not last:
            kind = ("a marked deload at the other gym"
                    if newer["date"] in deload_set and newer["context_change"]
                    else "a marked deload" if newer["date"] in deload_set
                    else "at the other gym")
            newer_s = f"the newer session on {newer['date']} was {kind}"
        ref_age = (today_d - _parse_iso_date(last["date"])).days

        # The ladder's order is the precedence. Evidence that the last
        # session is not a basis for progress (a long gap, no usual-gym
        # session at all) comes before the policy; the policy comes before
        # the log's own verdict, because a red-flag day can only take a bump
        # away, never grant one.
        new_load = load
        rederive = False
        discount = 1.0
        if not usual:
            action = "hold"
            basis = (f"every logged session of this lift is tagged as a "
                     f"different gym or machine (latest {last['date']}: "
                     f"{done}), so there is no usual-gym load to compare "
                     f"against and nothing earned: repeat it")
        elif days_since >= STALE_EXERCISE_DAYS:
            action = "hold"
            when = (f"last worked {days_since} days ago ({done})"
                    if newer_s is None else
                    f"last worked {days_since} days ago ({newer_s}); the "
                    f"reference session was {last['date']}, {ref_age} days "
                    f"ago ({done})")
            basis = (f"{when}: a re-entry, so no progression and the load "
                     f"is re-derived from the best set")
            rederive = True
            if days_since > ROTATION_CANDIDATE_WINDOW_DAYS:
                discount = NOVELTY_DISCOUNT
            if lo is None:
                med = statistics.median(reps)
                lo, hi = _ladder_range(med, cls)
                range_s = _range_str(lo, hi)
                source = f"derived from last session reps (median {med:g})"
                basis += (f". No rep range is on record, so {range_s}, the "
                          f"standard range that holds the last session's "
                          f"median of {med:g} reps (capped at the {cls} "
                          f"ceiling), stands in")
        elif policy == "reduce":
            action = "reduce"
            basis = (f"load policy is reduce: deload, hold {load:g}kg and "
                     f"cut sets")
        elif hi is None:
            action = "hold"
            basis = (f"{done}, but no rep range is on record for this lift "
                     f"(no plan or block prescribes one), so there is no "
                     f"top of range to judge against")
        elif hi < NEXT_DOSE_MIN_TOP_REPS:
            action = "hold"
            basis = (f"{done}, but the prescription tops out at {hi} "
                     f"rep{'s' if hi != 1 else ''}, a heavy single or double "
                     f"that reps cannot show is earned: repeat {load:g}kg "
                     f"and add load by effort, not automatically")
        elif earned:
            action = "add_load"
            new_load = round(load + inc, 2)
            basis = (f"every set hit the top of {range_s} ({done}): "
                     f"+{inc:g}kg and the reps start again from {lo}")
        else:
            action = "add_reps"
            if top_hit:
                short = (f"only {last['sets']} working set was logged"
                         if last["sets"] < NEXT_DOSE_MIN_SETS_AT_LOAD else
                         f"only {len(reps)} of {last['sets']} sets were at "
                         f"that load")
                basis = (f"{done}, but {short}, too few "
                         f"({NEXT_DOSE_MIN_SETS_AT_LOAD} needed) to call the "
                         f"top of {range_s} earned: {{keep}}aim for more reps")
            else:
                basis = (f"{done}, short of the top of {range_s}: {{keep}}aim "
                         f"for more reps")
                if lo is not None and max(reps) < lo:
                    # Below the bottom of the range. One such session keeps
                    # the load; the same miss in the session before it, at
                    # this load, takes it down.
                    prev = usual[-2] if len(usual) >= 2 else None
                    plo, phi, _src = (
                        _prescribed_range(key, prev["date"], plan_slots,
                                          block_slots, prev, rows, catalog)
                        if prev else (None, None, None))
                    prev_lo = _normalise_range(plo, phi, cls)[0]
                    rederive = prev is not None and _missed_bottom_at(
                        prev, load, prev_lo if prev_lo is not None else lo)
                    if rederive:
                        basis += (f". The best set was under {lo}, the "
                                  f"bottom of the range, in the last two "
                                  f"sessions at {load:g}kg too")
                    else:
                        basis += (f". The best set was under {lo}, the bottom "
                                  f"of the range, but one session is not "
                                  f"enough to cut the load: the next miss at "
                                  f"{load:g}kg drops it")

        # A load the lifter could not do. The lift lapsed, or the best set
        # fell short of the bottom of the range in each of the last two
        # sessions at this load, so repeating the load asks for a set the log
        # says is out of reach: re-derive it from the best set at the bottom
        # of the range, never up, to the NEAREST step. A shortfall under half
        # a step lands on the last load, which is kept.
        lowered = False
        if rederive:
            d_load, e1rm, raw = rep_matched_load(
                last, lo, load, inc, discount)
            proj = (f"The best set projects an e1RM of {e1rm:.1f}kg, about "
                    f"{raw / discount:.1f}kg for {lo} reps")
            if discount != 1.0:
                proj += (f"; the {days_since}-day gap is over "
                         f"{ROTATION_CANDIDATE_WINDOW_DAYS} days, so the "
                         f"{discount:g} first-exposure discount (the one "
                         f"rotation_candidates uses) takes that to "
                         f"{raw:.1f}kg")
            if d_load < load - 1e-9:
                lowered = True
                new_load = d_load
                basis += (f". {proj}; load_kg rounds that to the nearest "
                          f"{inc:g}kg step: {d_load:g}kg")
            elif raw < load - 1e-9:
                basis += (f". {proj}, which rounds to the nearest {inc:g}kg "
                          f"step back to the last load: {load:g}kg stays"
                          + ("" if days_since >= STALE_EXERCISE_DAYS else
                             ", and the stall rule handles a lift that "
                             "does not move"))
            elif discount != 1.0:
                basis += (f". {proj}, which is not below the last load, so "
                          f"it is repeated: {load:g}kg")
        if newer_s is not None and days_since < STALE_EXERCISE_DAYS:
            basis += (f". Reference session {last['date']} ({ref_age} days "
                      f"ago); {newer_s}")
        basis = basis.replace("{keep}", "" if lowered else "same load, ")
        if note:
            basis = f"{note}; {basis}"

        stalled = load_stall_sessions(full, deload_set,
                                      REP_CEILING_RANGE[cls][1])
        entry = {
            "exercise":         name,
            "load_kg":          new_load,
            "rep_range":        range_s,
            "action":           action,
            "basis":            basis,
            "last":             f"{last['date']}: {done}",
            "last_load_kg":     load,
            "last_reps":        list(reps),
            "sessions_at_load": _sessions_at_load(usual or sessions),
            "stalled_sessions": stalled or None,
            "range_from":       source,
            "increment_kg":     inc,
            "increment_basis":  inc_basis,
        }
        if usual and other is not None:
            other_load = _working_load(other)[0]
            if not loads_equal(other_load, load):
                entry["other_gym_load_kg"] = other_load
        entries.append(entry)

    entries.sort(key=lambda e: e["exercise"].lower())
    uncovered.sort(key=lambda u: u["exercise"].lower())
    return {
        "load_policy": policy,
        "exercises":   entries,
        "uncovered": ({"reason": UNCOVERED_REASON,
                       "exercises": uncovered} if uncovered else None),
    }
