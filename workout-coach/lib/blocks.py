"""Training blocks: stable anchors, rotating accessories, and the
boundary that forces the rotation to actually happen (D2).

Three things live here, and they are one idea seen from three sides.

**Pattern identity.** Rotation means changing what a slot TRAINS, not
what it is called. ``Cable Lateral Raise -> Dumbbell Lateral Raise``
changes the equipment word and nothing else: same muscle, same movement
pattern, same joint action, same catalog subsection. Every check below
compares ``pattern_group`` — the catalog's own ``## MUSCLE`` heading plus
``### Subsection`` — because that is where the repo already records what
a movement is. Equipment is deliberately NOT part of the identity.

**The block artifact.** ``plans/<Person>/block-<start>.json`` records,
per session type and per slot, the exercise and whether the slot is an
``anchor`` (persists 2-3 blocks) or ``rotating`` (must change every
block). Without a written record there is nothing for generation N+1 to
differ FROM, which is the root cause the whole workstream addresses.

**The boundary.** A block ends at the deload or at six weeks, whichever
comes first — computed here, not asserted in prose, because the cadence
deload has been skipped twice and a six-week ceiling that only exists in
a prompt does not fire.

Public surface:

- ``load_pattern_catalog(db)`` — ``{name_lower: {muscle, section,
  pattern, equipment, is_compound}}``.
- ``pattern_group(exercise, catalog)`` — the pattern identity string.
- ``read_block(person)`` / ``write_block(person, block)`` /
  ``new_block(...)``.
- ``block_status(block, today_d, deloads)`` — age, boundary, reason.
- ``rotation_diff_errors(prev_block, new_block, catalog)`` — the
  blocking-error list W4's render validator calls.
- ``core_spec_conflicts(block, catalog, spec, db)`` — which
  ``core_week_spec`` axes this block's own core slots violate, so an
  artifact from the pre-spec era cannot be copied forward silently
  (R-05).
- ``strip_benched_slots(block, benched)`` — a movement the ledger has
  withdrawn must not survive in a slot the coach is told to copy.
- ``reconcile_block_with_logs(block, rows, db, catalog, start, end)`` —
  fold gym-floor substitutions back into the artifact at the boundary.
- ``derived_starting_load(exercise, e1rm, catalog, db, target_reps)`` —
  a legal starting weight for a movement with no history.
- ``rotation_candidates(...)`` — those derivations, for the payload.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

# ``session_key`` / ``session_type_from_title`` are defined in
# ``adherence`` because they parse a PLAN HEADING, which is that
# module's grammar. They are imported rather than restated here: block
# slots are grouped by the same key the ledger groups sessions by, and
# two implementations of that key would silently desync the two.
# The dependency runs one way only — ``adherence`` never imports this
# module.
from .adherence import (
    load_plans,
    session_key,
    session_type_from_content,
    session_type_from_title,
)
from .constants import CORE_WEEK_SPEC
from .parsing import _parse_iso_date
from .sessions import _is_working_set


# A block runs six weeks at the outside. RP-style mesocycles are 4-6
# weeks of accumulation before a deload; six is the ceiling, not the
# target. The rule is expressed in days so the arithmetic is exact.
BLOCK_MAX_WEEKS = 6
BLOCK_MAX_DAYS = BLOCK_MAX_WEEKS * 7

# An anchor is allowed to persist this many blocks before it must be
# reconsidered. Three blocks at six weeks is ~18 weeks on one movement,
# which is past the point where the specific-exercise adaptation has run
# out even on the generous readings of the literature.
ANCHOR_MAX_BLOCKS = 3

# The routine deload cadence, in weeks since the last USER-MARKED
# deload. Same number as BLOCK_MAX_WEEKS and a different clock: block age
# counts from the last exercise-selection change, this counts from the
# last time volume was actually cut. They are reset by different events
# and routinely disagree — see `deload_cadence`.
DELOAD_CADENCE_WEEKS = 6

SLOT_TAGS = ("anchor", "rotating")
ANCHOR_CHANGE_REASONS = ("stall_3_sessions", "injury", "age_3_blocks",
                         "user_substitution")

# Which of those a COACH may assert, and which the system must derive.
#
# ``user_substitution`` exists because the ledger records real gym-floor
# swaps — a movement replaced by hand, logged repeatedly — and prescribing
# what the user demonstrably performs is what the prompt asks for. Before
# this token the only honest options were to take a spurious warning or to
# write one of the other three as a lie, and both were observed.
#
# It is DERIVED ONLY, and that is the whole point of separating the two
# tuples. The other three are either facts the payload holds
# (``stall_3_sessions``, ``age_3_blocks``) or a fact only the user knows
# and states once (``injury``). ``user_substitution`` is a claim ABOUT THE
# LEDGER, so the ledger has to be the one making it: it is granted by
# ``_anchor_change_excuse`` when ``reconcile_block_with_logs`` stamped
# ``performed_instead`` on the dropped anchor AND the replacement is that
# performed movement. A coach cannot reach it by writing anything —
# ``adherence._ANCHOR_CHANGE_RE`` does not accept the token, and rule 5
# only honours declarations drawn from the tuple below. That keeps the
# deciding input in the user-log provenance class rather than in
# coach-authored free text, which is where every exploit in this system
# has lived.
COACH_DECLARABLE_ANCHOR_CHANGE_REASONS = ("stall_3_sessions", "injury",
                                          "age_3_blocks")

# How many previous occupants of a rotating slot are remembered. A slot
# that alternates Plank / Dead Bug / Bird Dog forever changes its
# exercise every block and rotates nothing; three blocks of memory is
# what makes that visible to a pairwise check, because the memory
# travels inside the previous block.
ROTATION_HISTORY_DEPTH = 3

# How many accessory slots one compound can host. A compound's value as a
# host is its long rest period, and a 4-set compound has four of those.
# An accessory wants three sets, so two accessories per compound is the
# practical ceiling — declaring six accessories supersetted onto one
# squat is not a superset, it is a way of writing "supersetted" six times.
SUPERSET_HOST_CAPACITY = 2

# Consecutive sessions at the same load and reps before an anchor may be
# swapped without a human saying so. Same number SKILL.md's stall-response
# rule uses, and it is the number that makes ``stall_3_sessions`` a
# DERIVABLE reason rather than a field only a hand-edited artifact could
# ever carry — see ``_anchor_change_excuse``.
ANCHOR_STALL_SESSIONS = 3

# How much of a session's identity has to survive for two differently
# NAMED sessions to be the same session. Renaming a heading
# (``LOWER A + CORE`` -> ``LOWER 1 + CORE``) changed the ``session_key``
# and silently exempted the whole session from every rotation rule: 27
# errors became 0. Matching therefore falls back to content — the
# exercises, or, at a boundary where the exercises are supposed to
# change, the movement patterns. The floor is the same 0.34 the ledger's
# own session matcher uses, for the same reason: a faithful partial
# execution of a session is still that session.
SESSION_MATCH_MIN_OVERLAP = 0.34

# Equipment words that are flavour, not identity. Used only by the
# belt-and-braces name check in ``rotation_diff_errors``: if the catalog
# ever mis-files two flavours of one movement under different
# subsections, the pattern check would pass and this one still fails.
_EQUIP_WORDS = frozenset({
    "barbell", "bb", "dumbbell", "db", "cable", "machine", "smith",
    "landmine", "band", "plate", "bodyweight", "bw", "kettlebell", "kb",
    "ez", "ez-bar", "rope", "bar",
})
_WORD_RE = re.compile(r"[a-z0-9]+")


# ------------------------------------------------------- pattern identity
def load_pattern_catalog(db: dict | None = None) -> dict[str, dict]:
    """Catalog entries keyed by lowercased name, carrying pattern identity.

    Built from ``shared.exercises_database.parse_database()`` — the same
    parser ``/log``'s proposal flow and the core-category validator read.
    That parser is used rather than ``extract.load_exercises_db`` because
    the coach parser resolves every subsection down to a ``primary``
    muscle and throws the subsection away; ``QUADS/Squat Pattern
    (Compound)`` and ``QUADS/Quad Isolation`` both come out as
    ``primary: quads``, which cannot answer "is this the same movement
    pattern". Only ``parse_database`` keeps the structure.

    ``equipment`` and the synergist fallback for ``is_compound`` come
    from ``db`` when supplied (``extract.load_exercises_db``'s output) —
    reusing that parse rather than re-deriving the bracket tags here.

    ``is_compound`` reads the subsection heading: a heading containing
    "compound" is compound, one containing "isolation" is not. Headings
    that say neither (CALVES, ADDUCTORS, ``Traps``) fall back to "has at
    least one synergist", which is the same operational definition the
    volume model uses.

    CORE IS EXEMPT FROM THAT FALLBACK. ``is_compound`` decides two
    things here — whether a slot is inferred as an ``anchor``, and
    whether it may HOST a superset — and neither is true of trunk work.
    The catalog's own CORE preamble defines the section as "the
    abdominal wall", so a synergist list on a core entry names grip or
    postural involvement, not a second trained region. Exactly one entry
    is affected: ``Suitcase Carry`` carries ``+traps, +forearms`` under
    ``### Anti-Lateral-Flexion`` (a heading that says neither word) and
    was therefore tagged an anchor — wrong for a carry, and it left the
    Anti-Lateral-Flexion rotating pool with one member.
    """
    from shared.exercises_database import entry_canonical_name, parse_database

    parsed = parse_database()
    out: dict[str, dict] = {}
    for muscle in parsed.get("__muscle_order__", []):
        mb = parsed["muscles"][muscle]
        for section in mb["__section_order__"]:
            for entry in mb["sections"][section]:
                name = entry_canonical_name(entry).strip()
                if not name:
                    continue
                key = name.lower()
                sect = "" if section == "_default" else section
                low = sect.lower()
                if "compound" in low:
                    is_compound = True
                elif "isolation" in low:
                    is_compound = False
                else:
                    is_compound = None
                meta = (db or {}).get(key) or {}
                if is_compound is None and muscle != "CORE":
                    is_compound = bool(meta.get("synergists")) or None
                out[key] = {
                    "name":        name,
                    "muscle":      muscle,
                    "section":     sect,
                    "pattern":     f"{muscle}/{sect}" if sect else muscle,
                    "equipment":   meta.get("equipment"),
                    "primary":     meta.get("primary"),
                    "is_compound": is_compound,
                    "is_warmup":   meta.get("is_warmup", muscle == "WARMUP"),
                    "is_cardio":   meta.get("is_cardio", muscle == "CARDIO"),
                }
    return out


def pattern_group(exercise: str, catalog: dict | None) -> str | None:
    """``"<MUSCLE>/<Subsection>"`` for ``exercise``, or ``None`` if off-catalog.

    ``None`` is load-bearing: a slot whose exercise is not in the catalog
    cannot have its rotation verified, and ``rotation_diff_errors``
    treats that as a blocking error rather than a pass. Otherwise the
    cheapest way past a rotation check would be to invent a name.
    """
    meta = (catalog or {}).get((exercise or "").strip().lower())
    return meta["pattern"] if meta else None


def _identity_words(name: str) -> frozenset[str]:
    return frozenset(w for w in _WORD_RE.findall((name or "").lower())
                     if w not in _EQUIP_WORDS)


def _equipment_flavour_only(a: str, b: str) -> bool:
    """True when two names differ ONLY by an equipment word.

    ``Cable Lateral Raise`` vs ``Dumbbell Lateral Raise`` -> True.
    ``Leg Curl (Seated)`` vs ``Leg Curl (Lying)`` -> False.
    """
    if (a or "").strip().lower() == (b or "").strip().lower():
        return False
    wa, wb = _identity_words(a), _identity_words(b)
    return bool(wa) and wa == wb


# --------------------------------------------------------- the artifact
def new_block(start_date: str, sessions: dict[str, list[dict]] | None = None,
              prev_block: dict | None = None) -> dict:
    """Build a block artifact.

    ``sessions`` maps a session-type key (``lower_a``, ``upper_b``, …) to
    an ordered slot list. Each slot needs at least ``exercise`` and
    ``tag``; ``position`` is filled in from the order, and
    ``blocks_held`` counts up from the previous block when the anchor
    survived, which is what makes ``ANCHOR_MAX_BLOCKS`` checkable.
    """
    prev_held: dict[tuple[str, str], int] = {}
    prev_slot: dict[tuple[str, int], dict] = {}
    for stype, slots in ((prev_block or {}).get("sessions") or {}).items():
        for i, s in enumerate(slots, start=1):
            prev_held[(stype, (s.get("exercise") or "").lower())] = int(
                s.get("blocks_held") or 1)
            prev_slot[(stype, int(s.get("position") or i))] = s
    built: dict[str, list[dict]] = {}
    for stype, slots in (sessions or {}).items():
        out = []
        for i, s in enumerate(slots, start=1):
            tag = s.get("tag") or "rotating"
            pos = int(s.get("position", i))
            held = prev_held.get((stype, (s.get("exercise") or "").lower()), 0)
            prev = prev_slot.get((stype, pos)) or {}
            # Slot memory: the occupants this position has already had,
            # newest first. Carried forward so a one-block-lookback check
            # can still see three blocks of rotation.
            history = [h for h in
                       ([prev.get("exercise")] + list(prev.get("history") or []))
                       if h][:ROTATION_HISTORY_DEPTH]
            entry = {
                "position":    pos,
                "exercise":    (s.get("exercise") or "").strip(),
                "tag":         tag if tag in SLOT_TAGS else "rotating",
                "blocks_held": held + 1,
                "history":     history,
            }
            for opt in ("pattern", "superset_with", "superset_hint_unresolved",
                        "anchor_change_reason", "dose",
                        "substituted_from", "at_risk", "stalled_sessions",
                        "performed_instead"):
                if s.get(opt) is not None:
                    entry[opt] = s[opt]
            out.append(entry)
        built[stype] = out
    return {
        "version":         1,
        "block_id":        start_date,
        "started":         start_date,
        "age_weeks":       0.0,
        "boundary_due":    False,
        "boundary_reason": None,
        "boundary_due_by": (
            (_parse_iso_date(start_date) + timedelta(days=BLOCK_MAX_DAYS)).isoformat()
            if _parse_iso_date(start_date) else None),
        "sessions":        built,
    }


def _catalog_identity_vocabulary(catalog: dict | None) -> frozenset[str]:
    """Every identity word that appears in any canonical exercise name.

    The discriminator `_match_superset_host` uses to tell a truncated
    exercise name from trailing prose. ``press`` and ``calf`` are in here;
    ``above``, ``leave`` and ``tank`` are not.
    """
    out: set[str] = set()
    for name in (catalog or {}):
        out |= _identity_words(name)
    return frozenset(out)


def _match_superset_host(hint: str, slots: list[dict],
                         vocabulary: frozenset[str] | None = None) -> str | None:
    """Resolve a prose superset hint to a slot name in the same session.

    The plan writes "superset with the calf raise above"; the slot is
    called "Dumbbell Standing Calf Raise". Match on word containment,
    which is exact enough for the plan's own vocabulary and refuses to
    guess when two slots would both match.

    TRAILING PROSE IS TOLERATED. ``adherence._SUPERSET_RE`` strips a bare
    trailing direction word because it anchors on end-of-line, so
    ``— superset with the cable lat pulldown above`` arrives as
    ``cable lat pulldown`` and resolved, while
    ``— superset with the cable lat pulldown above, leave 2-3 in the
    tank`` arrived whole and resolved to nothing. The pairing WAS written;
    only the parse failed, and the resulting error then told the coach the
    slot had been "left standalone", which was false. Splitting the note
    in two was the documented remedy and it inflated the sub-bullet count,
    so one warning manufactured another.

    The fix is a prefix backoff: try the longest run of leading identity
    words that resolves to exactly one slot, shortening one word at a
    time.

    THE GUARD, and the wrong question the first version answered. Its
    docstring argued the backoff "cannot resolve an ambiguity either —
    dropping a word can only ever ADD candidates", which is true and
    beside the point. The failure is not an ambiguity resolved wrongly;
    it is a hint whose intended host is ABSENT, where a generic leading
    word then manufactures a unique hit. Three confirmed on real
    vocabulary: ``the leg press above`` resolved to ``Leg Extension``
    (dropping ``press`` and matching on ``leg``), ``the seated calf raise
    above`` to ``Seated Cable Row``, ``the chest press above`` to ``Chest
    Supported Row Machine``. All three answered ``None`` before the
    backoff was added, so the backoff made them worse than the bug it
    fixed: a wrong pairing is asserted onto the block artifact and travels
    into the next generation's rotation diff.

    So the winning prefix may only have dropped PROSE. The word
    immediately after it is checked against the catalog's identity
    vocabulary: ``above`` / ``leave`` / ``tank`` are not exercise words
    and the match stands; ``press`` / ``calf`` / ``raise`` are, which
    means the referent's own name was truncated to force the hit, and the
    answer is ``None``. Under-specified references still resolve —
    ``the squat above`` finds ``Barbell Back Squat``, ``the bench press
    above`` finds ``Dumbbell Flat Bench Press`` — because what follows
    them is prose, not a dropped name word.

    ``vocabulary`` falls back to the session's own slot words when no
    catalog is supplied. That is weaker (it cannot see that ``press`` is
    an exercise word when no press is in this session) and it is the
    caller's job to pass the catalog it already has.
    """
    words = [w for w in _WORD_RE.findall((hint or "").lower())
             if w not in _EQUIP_WORDS]
    if not words:
        return None
    names = [(s.get("exercise") or "", _identity_words(s.get("exercise") or ""))
             for s in slots]
    if vocabulary is None:
        vocabulary = frozenset().union(*(have for _n, have in names)) \
            if names else frozenset()
    for n in range(len(words), 0, -1):
        want = frozenset(words[:n])
        hits = [name for name, have in names if want <= have]
        if len(hits) != 1:
            continue
        if n < len(words) and words[n] in vocabulary:
            # The prefix won by truncating the exercise name it was
            # referring to, not by shedding prose. The referent is not in
            # this session; say so instead of guessing a neighbour.
            return None
        return hits[0]
    return None


def block_from_plan(plan: dict, catalog: dict, start_date: str | None = None,
                    prev_block: dict | None = None) -> dict:
    """Bootstrap a block artifact from a parsed plan.

    The first run has no block on disk, so there is nothing for the next
    generation to differ from and every rotation check would vacuously
    pass. Deriving the block from the plan that was actually prescribed
    closes that: generation N+1 is compared against what N really said.

    Slot tags are inferred, not invented — a compound is an ``anchor``
    (progression needs something to accumulate on), an isolation slot is
    ``rotating``. The coach may retag when it writes the next block; the
    inference only has to be a defensible starting point.
    """
    plan_date = start_date or plan.get("plan_date")
    # Once per plan, not once per workout: `_match_superset_host` needs it
    # for every hint and it is a full pass over the catalog.
    vocabulary = _catalog_identity_vocabulary(catalog)
    sessions: dict[str, list[dict]] = {}
    for w in plan.get("workouts") or []:
        key = session_key(w.get("title") or "", w.get("index") or 0)
        slots: list[dict] = []
        for s in w.get("slots") or []:
            if s.get("prescribed_sets", 0) <= 0:
                continue
            meta = catalog.get(s["exercise"].strip().lower()) or {}
            if meta.get("is_warmup") or meta.get("is_cardio"):
                continue
            entry = {
                "exercise": s["exercise"].strip(),
                "tag":      "anchor" if meta.get("is_compound") else "rotating",
                "pattern":  meta.get("pattern"),
                "position": len(slots) + 1,
                "superset_hint": s.get("superset_hint"),
                # WHAT THIS SLOT WAS PRESCRIBED, carried on the artifact so
                # generation N+1 can tell "carried forward and progressed"
                # from "carried forward and re-copied". The block already
                # records WHICH movements a session held; without the dose
                # it cannot answer the complaint the whole workstream
                # started from ("every plan is the same plan"), because an
                # identical prescription and a progressed one look the
                # same. Field names match `adherence._slot_from_bullet`
                # exactly so `adherence._dose_delta` — the one definition
                # of "did the dose materially move" — reads this dict
                # directly instead of a translated copy.
                "dose": {
                    "load_kg":         s.get("load_kg"),
                    "rep_lo":          s.get("rep_lo"),
                    "rep_hi":          s.get("rep_hi"),
                    "rep_target":      s.get("rep_target"),
                    "prescribed_sets": s.get("prescribed_sets"),
                },
            }
            # The plan's own sub-bullet is the only channel a human has
            # for the one anchor-change reason nothing can derive.
            # ``stall_3_sessions`` comes off the e1RM stall counter and
            # ``age_3_blocks`` off ``blocks_held``; ``injury`` is a fact
            # only the user knows, and until this grammar existed the
            # validator demanded a field the plan format could not
            # express. See ``adherence._ANCHOR_CHANGE_RE``.
            #
            # Filtered against the DECLARABLE tuple, not the full enum.
            # This side reads a coach-authored hint, and
            # ``user_substitution`` is a claim about the LEDGER that only
            # `_anchor_change_excuse` may grant — the whole reason the two
            # tuples exist. Reading the full enum here made the separation
            # depend on `adherence._ANCHOR_CHANGE_RE` refusing the token,
            # which is one parser edit away from being untrue, and left a
            # programmatically built plan dict able to assert it directly.
            if s.get("anchor_change_hint") in COACH_DECLARABLE_ANCHOR_CHANGE_REASONS:
                entry["anchor_change_reason"] = s["anchor_change_hint"]
            slots.append(entry)
        for s in slots:
            hint = s.pop("superset_hint", None)
            if hint:
                host = _match_superset_host(hint, slots, vocabulary)
                if host and host != s["exercise"]:
                    s["superset_with"] = host
                else:
                    # The pairing WAS written and could not be resolved to
                    # a slot in this session. Kept so rule 6 can say that
                    # instead of "left standalone", which is a different
                    # defect with a different remedy — see
                    # `_superset_errors`.
                    s["superset_hint_unresolved"] = hint
        if slots:
            sessions[key] = slots

    # ADHERENCE AND STALL FACTS TRAVEL BY EXERCISE NAME (W5 F3).
    #
    # The proposed block always comes from the plan markdown, which
    # cannot state either. ``at_risk`` was read off the NEW block by rule
    # 6 and the new block never had it: 23 slots carried the flag on the
    # previous artifact and 0 on the proposal, so the adherence-driven
    # half of the superset rule was dead code — mutating
    # ``AT_RISK_COMPLETION`` from 0.5 to 0.0 survived the whole suite.
    #
    # By NAME, not by position or by session: the fact is about the
    # movement ("this one keeps not getting done", "this one has not moved in
    # four sessions"), so it must follow the movement wherever the next
    # plan puts it.
    carried: dict[str, dict] = {}
    for slots in ((prev_block or {}).get("sessions") or {}).values():
        for s in slots:
            key = (s.get("exercise") or "").strip().lower()
            if key:
                carried[key] = s
    for slots in sessions.values():
        for s in slots:
            prev = carried.get(s["exercise"].strip().lower()) or {}
            for field in ("at_risk", "stalled_sessions"):
                if prev.get(field) is not None and s.get(field) is None:
                    s[field] = prev[field]

    block = new_block(plan_date, sessions, prev_block=prev_block)
    block["derived_from_plan"] = plan.get("plan_date")
    # Provenance, so a consumer can tell a block that was WRITTEN DOWN
    # from one reconstructed on the fly. ``write_block`` overwrites this
    # with ``artifact``; the read path leaves it, and the render
    # validator's self-diff guard keys on it. See ``block_payload``.
    block["source"] = "derived_from_plan"
    # CONTENT-CHECKED, not read off the heading (R-13). A session type
    # decides the per-session core budget, and the heading is free text
    # the coach writes — `## Workout 1: PUSH` full of squats classified
    # confidently as an upper day and bought the 2-set budget. The plan's
    # own bullets are passed so the name has to survive them.
    block["session_types"] = {
        session_key(w.get("title") or "", w.get("index") or 0):
            session_type_from_title(w.get("title"), w.get("slots"))
        for w in plan.get("workouts") or []
    }
    return block


def read_block(person: str) -> dict | None:
    """Newest persisted block for ``person``, or ``None`` before the first."""
    from shared.person_paths import latest_block_json
    p = latest_block_json(person)
    if p is None or not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_block(person: str, block: dict) -> Path:
    """Persist ``block`` to ``plans/<Person>/block-<started>.json``.

    Writing is what turns a derived block into a record, so the stored
    copy says ``source: "artifact"`` whatever it was reconstructed from.
    The distinction is load-bearing: a derived block is regenerated from
    whichever plan happens to be newest, so its ``started`` moves under
    the reader's feet, and the render validator's "is this a self-diff"
    guard has to be able to tell the two apart.
    """
    from shared.person_paths import block_json, ensure_plans_dir
    started = block.get("started") or block.get("block_id")
    if not started:
        raise ValueError("block needs a 'started' date")
    block = {**block, "source": "artifact"}
    ensure_plans_dir(person)
    path = block_json(person, started)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(block, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)
    return path


def block_status(block: dict | None, today_d: date,
                 deloads: list[str] | None = None) -> dict:
    """Age and boundary state, always recomputed from ``started``.

    The artifact stores ``age_weeks`` / ``boundary_due`` so a human
    reading the file sees them, but they are derived, so they are derived
    HERE on every read. A stored boolean that nothing recomputes is how a
    six-week ceiling silently becomes a nine-week block.

    The boundary fires on whichever comes first:
      * a deload logged on or after ``started`` — the block has ended in
        fact, whatever the calendar says; or
      * ``BLOCK_MAX_WEEKS`` of age — the ceiling, which exists precisely
        because the cadence deload gets skipped.
    """
    if not block:
        return {"has_block": False, "age_weeks": None, "boundary_due": True,
                "boundary_reason": "no_block_on_record",
                "boundary_due_by": None, "started": None, "block_id": None}
    started = _parse_iso_date(block.get("started"))
    if started is None:
        return {"has_block": True, "age_weeks": None, "boundary_due": True,
                "boundary_reason": "unparseable_start_date",
                "boundary_due_by": None, "started": block.get("started"),
                "block_id": block.get("block_id")}
    age_days = (today_d - started).days
    age_weeks = round(age_days / 7.0, 1)
    deload_in_block = sorted(
        d for d in (deloads or [])
        if (_parse_iso_date(d) or date.min) >= started
        and (_parse_iso_date(d) or date.max) <= today_d
    )
    if deload_in_block:
        due, reason = True, f"deload_on_{deload_in_block[0]}"
    elif age_days >= BLOCK_MAX_DAYS:
        due, reason = True, f"age_{age_weeks}w_of_{BLOCK_MAX_WEEKS}w_ceiling"
    else:
        due, reason = False, None
    return {
        "has_block":       True,
        "block_id":        block.get("block_id"),
        "started":         block.get("started"),
        "age_weeks":       age_weeks,
        "boundary_due":    due,
        "boundary_reason": reason,
        "boundary_due_by": (started + timedelta(days=BLOCK_MAX_DAYS)).isoformat(),
        "deloads_in_block": deload_in_block,
    }


def _cadence_due_at(deloads: list[str] | None, as_of: date) -> bool:
    """Was a routine deload owed as of ``as_of``?

    True when the newest deload on or before ``as_of`` is at least
    ``DELOAD_CADENCE_WEEKS`` old, and when there is no deload on record
    at all — SKILL.md's "past 6 weeks (or empty ``deloads``)".
    """
    past = [d for d in (deloads or [])
            if (_parse_iso_date(d) or date.max) <= as_of]
    if not past:
        return True
    last = _parse_iso_date(max(past))
    if last is None:
        return True
    return (as_of - last).days >= DELOAD_CADENCE_WEEKS * 7


def deload_cadence(deloads: list[str] | None, today_d: date,
                   prior_generation: date | None = None) -> dict:
    """Whether THIS generation's plan is meant to be a low-volume week.

    Distinct from ``boundary_due``, and the distinction is the whole
    point of the field. ``boundary_due`` says "rotate the exercise
    selection"; this says "cut the volume". They run off different
    clocks — block age versus weeks since the last logged deload — and
    all four combinations occur:

      ``F/F``  a normal week mid-block.
      ``T/F``  the block aged out, or a deload was taken inside it, so
               the selection should rotate but the volume should not be
               cut again.
      ``F/T``  a young block whose cadence counter is old: the block was
               reopened on a split change while the deload counter kept
               running. This is the real 2026-07-13 case.
      ``T/T``  end of a mesocycle — rotate the selection AND cut volume.

    WHY "FIRST CROSSING" AND NOT "IS OWED". The cadence counter only
    resets when a deload is actually logged, so a declined deload leaves
    it climbing forever: one tracker sat at 6.4, 7.0, 7.3 and 8.3 weeks
    across four consecutive generations, of which exactly the first was a
    deload plan and the other three deliberately ran full volume. A flag
    on "is owed" would demote the volume floors to advisory on all four —
    relaxing the rules hardest on the weeks that most need them. So the
    flag fires on the generation where the cadence CROSSES, which is the
    generation SKILL.md tells the coach to prescribe the deload session
    in. ``cadence_due`` carries the standing "still owed" state
    separately, because nine weeks without a deload is worth saying out
    loud even when it does not relax anything.

    It is derived entirely from the deload log and the plan dates —
    never from the plan's contents. Reading it off set counts would let a
    coach unlock the relaxed floors by prescribing less, which is the
    gaming vector every other signal here is built to close.

    Known limitation, in the safe direction: if the user declines at the
    crossing and the coach re-offers weeks later, the re-offer is not
    flagged. Under-flagging keeps the floors blocking; over-flagging
    silently lowers them.

    This covers the PLANNED path only. A REACTIVE deload comes from the
    recovery gate (``render_validators.is_deload_week``); a caller that
    wants "is this a deload week at all" takes the OR of the two.
    """
    past = [d for d in (deloads or [])
            if (_parse_iso_date(d) or date.max) <= today_d]
    last = max(past) if past else None
    last_d = _parse_iso_date(last) if last else None
    weeks = (round((today_d - last_d).days / 7.0, 1)
             if last_d is not None else None)

    due = _cadence_due_at(deloads, today_d)
    was_due = (_cadence_due_at(deloads, prior_generation)
               if prior_generation is not None else False)
    prescribed = due and not was_due
    if not prescribed:
        reason = None
    elif last is None:
        reason = "no_deload_on_record"
    else:
        reason = f"cadence_{weeks}w_since_{last}"
    return {
        "prescribed":         prescribed,
        "cadence_due":        due,
        "weeks_since_deload": weeks,
        "last_deload":        last,
        "cadence_weeks":      DELOAD_CADENCE_WEEKS,
        "reason":             reason,
    }


# ----------------------------------------------- the W4-facing validator
def _slot_names(slots) -> set[str]:
    return {(s.get("exercise") or "").strip().lower()
            for s in slots or [] if (s.get("exercise") or "").strip()}


def _slot_patterns(slots, catalog) -> set[str]:
    out = set()
    for s in slots or []:
        pg = pattern_group(s.get("exercise"), catalog)
        if pg:
            out.add(pg)
    return out


def _coverage(a: set, b: set) -> float:
    """Share of the SMALLER set the two have in common.

    Coverage, not Jaccard, for the same reason ``adherence._match_sessions``
    uses coverage: a session that keeps most of what it had while gaining
    two new slots is still that session, and Jaccard penalises exactly
    that.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _pair_sessions(prev_sessions: dict, new_sessions: dict,
                   catalog: dict) -> tuple[dict, list, list]:
    """Map each new session type to the previous one it continues.

    ``(pairs, new_unmatched, prev_unmatched)``. Exact key match first;
    what is left over is matched on CONTENT — exercise names, or, at a
    boundary where the exercises are meant to change, movement patterns
    — so that renaming a heading cannot exempt a session from the
    rotation rules. Greedy, best score first, deterministic on ties.
    """
    pairs: dict[str, str] = {}
    prev_left = set(prev_sessions)
    for key in new_sessions:
        if key in prev_left:
            pairs[key] = key
            prev_left.discard(key)

    scored: list[tuple[float, str, str]] = []
    for nk in sorted(k for k in new_sessions if k not in pairs):
        nn = _slot_names(new_sessions[nk])
        npg = _slot_patterns(new_sessions[nk], catalog)
        for pk in sorted(prev_left):
            score = max(_coverage(nn, _slot_names(prev_sessions[pk])),
                        _coverage(npg, _slot_patterns(prev_sessions[pk], catalog)))
            if score >= SESSION_MATCH_MIN_OVERLAP:
                scored.append((score, nk, pk))
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_new: set[str] = set()
    used_prev: set[str] = set()
    for _score, nk, pk in scored:
        if nk in used_new or pk in used_prev:
            continue
        pairs[nk] = pk
        used_new.add(nk)
        used_prev.add(pk)

    matched_prev = set(pairs.values())
    return (pairs,
            sorted(k for k in new_sessions if k not in pairs),
            sorted(k for k in prev_sessions if k not in matched_prev))


def _boundary_state(prev_block: dict | None,
                    new_block: dict | None) -> tuple[bool, str]:
    """``(is_boundary, basis)`` for a proposed block against its predecessor.

    Spec §4 W5.4 makes rotation a BOUNDARY rule, and the payload agrees
    with it: ``block_payload`` emits ``must_rotate`` only when
    ``boundary_due``. The validator did not, so it demanded a full
    rotation on every generation — 27 blocking errors and exit 2 against
    a payload whose own answer was "nothing must rotate", 1.1 weeks into
    a six-week block.

    Three sources, in order:

    1. ``prev_block["boundary_due"] is True`` — an explicit, already
       computed answer (``block_status`` recomputes it on every read and
       it is the only thing that can see a DELOAD inside the block, which
       ends a block whatever the calendar says). Only True is honoured:
       the persisted artifact stores a ``boundary_due`` that was false
       when it was written and stays false forever, so a stored False
       must never suppress the check.
    2. The dates. ``new["started"]`` is the plan being proposed and
       ``prev["started"]`` is when the block began, so their difference
       IS the block's age — the same arithmetic ``block_status`` does
       against ``today``.
    3. Unparseable dates read as a boundary. "I cannot establish that we
       are inside a block" has to fail closed, which is the same answer
       ``block_status`` gives for a missing block.
    """
    prev = prev_block or {}
    if prev.get("boundary_due") is True:
        return True, str(prev.get("boundary_reason") or "declared_boundary_due")
    started = _parse_iso_date(prev.get("started"))
    proposed = _parse_iso_date((new_block or {}).get("started"))
    if started is None or proposed is None:
        return True, "unknown_block_dates"
    weeks = round((proposed - started).days / 7.0, 1)
    if (proposed - started).days >= BLOCK_MAX_DAYS:
        return True, f"age_{weeks}w_of_{BLOCK_MAX_WEEKS}w_ceiling"
    return False, f"mid_block_{weeks}w"


def _is_self_diff(prev_block: dict | None, new_block: dict | None) -> str | None:
    """Why this pair cannot be diffed, or ``None`` when it can.

    A block DERIVED from a plan is not a record — it is rebuilt from
    whichever plan is newest, so the moment the plan being validated
    lands on disk the "previous" block becomes that same plan and the
    diff compares it against itself. Measured: plan 2026-07-25 already on
    disk gave 0 rotation errors, the identical inputs with the plan not
    yet written gave 27. That is the agent's own recovery loop — write
    plan, render fails, re-run, passes.

    ``block_payload`` now steps back a generation so this does not
    normally arise; this is the backstop, and it names the condition
    instead of silently returning a clean bill.
    """
    prev, new = prev_block or {}, new_block or {}
    if not prev.get("sessions"):
        return "no previous block to differ from"
    started, proposed = prev.get("started"), new.get("started")
    if started and proposed and started == proposed:
        origin = ("it was derived from this same plan"
                  if prev.get("source") == "derived_from_plan"
                  else "both blocks start on the same date")
        return (f"the previous block starts on {started}, the same date as "
                f"the proposal, so {origin}; rotation cannot be verified "
                f"against it")
    return None


def _anchor_change_excuse(prev_slot: dict,
                          new_names: "set[str] | None" = None) -> str | None:
    """A qualifying reason to drop this anchor, derived where it can be.

    ``anchor_change_reason`` used to be settable only by hand-editing an
    artifact, which nothing in the pipeline does — so a lift with
    ``stalled_sessions: 4``, whose stall response SKILL.md marks
    REQUIRED, could not legally be swapped. Three of the four reasons are
    facts the payload already holds, so they are read rather than asked
    for:

      ``age_3_blocks``     — ``blocks_held`` reached ``ANCHOR_MAX_BLOCKS``.
      ``stall_3_sessions`` — ``stalled_sessions`` reached
                             ``ANCHOR_STALL_SESSIONS``, threaded from
                             ``estimated_1rm`` by ``block_payload``.
      ``user_substitution`` — ``reconcile_block_with_logs`` found that the
                             prescribed movement was never logged in this
                             block's window while a same-pattern movement
                             WAS, and stamped that movement on the slot as
                             ``performed_instead``.

    ``injury`` stays human-supplied: nothing in the tracker knows it.
    It comes in through the plan's own sub-bullet grammar
    (``— anchor change: injury``) and lands on the new slot.

    ``new_names`` is the lowercased exercise-name set of the session that
    replaces this one, and it is what keeps ``user_substitution`` honest.
    The ledger's claim is narrow — "the user did X instead of Y" — so it
    excuses exactly one edit: prescribing X. Dropping Y for something the
    user never performed is a different decision and needs a different
    reason. Passing ``None`` (no session to check against) falls back to
    the unqualified read, which is only reachable from a direct call.
    """
    if int(prev_slot.get("blocks_held") or 0) >= ANCHOR_MAX_BLOCKS:
        return "age_3_blocks"
    if int(prev_slot.get("stalled_sessions") or 0) >= ANCHOR_STALL_SESSIONS:
        return "stall_3_sessions"
    performed = (prev_slot.get("performed_instead") or "").strip().lower()
    if performed and (new_names is None or performed in new_names):
        return "user_substitution"
    return None


def rotation_diff_report(prev_block: dict | None, new_block: dict | None,
                         catalog: dict | None = None) -> dict:
    """The full finding set for a proposed block: errors AND notes.

    ``{"errors", "notes", "boundary", "boundary_basis", "diffable",
    "undiffable_reason", "sessions_matched"}``.

    ``rotation_diff_errors`` is the thin, signature-stable projection of
    this that the render validator calls; everything the caller cannot
    act on by editing the plan — a split change, a mid-block reshuffle,
    an un-diffable pair — comes out as a NOTE rather than as a blocking
    error, so it is reported instead of either blocking a legal plan or
    vanishing.

    WHICH RULES BIND WHEN. Rotation is a boundary rule; adherence and
    structure are not.

    Boundary only (rules 1, 1b, 2, 3, 4). Mid-block the correct
    behaviour for a rotating slot is to STAY PUT — that is what makes it
    a block — so demanding that it change every week is not a stricter
    reading of the spec, it is a different and incompatible one.

    Always (the catalog precondition, rule 5, rule 6, host capacity):

      * an off-catalog name has no verifiable pattern on any week;
      * an anchor is meant to persist two to three BLOCKS, so swapping
        one mid-block is a strictly larger deviation than swapping one at
        a boundary and the exemptions (stall, injury, age) are exactly
        the mid-block reasons;
      * rule 6 is driven by adherence, not by the calendar. Gating it on
        the boundary would switch off the chronically-skipped-isolation
        protection for five weeks in six, which is the whole reason it
        exists.

    Six rules, in the order a reader would ask about them:

    1. **A rotating slot must actually change.** An exercise that is
       rotating in this session and was in this session last block has
       not rotated. This is what catches the degenerate solution to a
       weekly distribution spec — ``Ab Crunch + Plank + Bird Dog``
       satisfies three distinct exercises and three pattern categories
       every week, forever, while rotating nothing.
    1b. **Moving it to another day is not rotating it either.** An
       exercise that was somewhere in the previous block and is now a
       rotating slot in a DIFFERENT session is a reshuffle. Rule 1 alone
       made shuffling the cheapest possible way to comply: the slot
       changed, the block trained nothing new.
    2. **It must not change back.** A slot may not return to any exercise
       this session held in the last ``ROTATION_HISTORY_DEPTH`` blocks.
       Rule 1 alone is satisfied by alternating two movements; the slot
       ``history`` lists are what make that visible from one block back.
    3. **Equipment is not a change.** ``Cable Lateral Raise ->
       Dumbbell Lateral Raise`` differs only by an equipment word: same
       muscle, same pattern, same joint action.
    4. **Every session must gain a genuinely new pattern.** At least one
       rotating slot per session type must land in a ``pattern_group``
       the session did not have. Without this, a block can legally
       progress every slot one rung inside its own category and never
       train a category it is missing — which on this data means
       anti-rotation and loaded carries stay at zero forever. Moving one
       rung WITHIN a pattern (``Plank -> Ab Wheel Rollout``) stays legal
       per slot; it just cannot be the whole block.
    5. **An anchor changes only for a named reason.** ``stall_3_sessions``,
       ``injury``, or ``age_3_blocks`` — declared on a new anchor slot,
       or DERIVED from the dropped anchor's own stall / age counters (see
       ``_anchor_change_excuse``). Anchors exist so progression has
       something to accumulate on; silently swapping one converts the
       block model back into "a different plan every week".
    6. **Rotated-in and at-risk accessory work is supersetted onto a
       compound.** Not "placed earlier" — placement was tried on
       2026-07-25 and the moved movements were still dropped at positions
       4 and 5 of 8. Isolation is what gets truncated (28% against 11%
       for compounds), so the fix has to remove it from the session's
       marginal-time budget: the slot must name a ``superset_with`` that
       is a compound appearing EARLIER in the same session, so the set
       happens inside that exercise's rest period.

       Two scopes: **rotated into this session** (not "into the block" —
       an accessory moved across from Tuesday is new work for Thursday,
       and scoping it to the block was half of the shuffling loophole),
       and any slot marked ``at_risk``. Compounds are exempt: a compound
       is the host, not the guest. A host may absorb at most
       ``SUPERSET_HOST_CAPACITY`` accessories; its value is its rest
       windows and it only has so many.

    IDENTITY, NOT POSITION. Every rule above compares exercise NAMES
    within a session, never slot ordinals. Positions come from counting
    non-warmup bullets, so inserting one accessory shifted every
    downstream position and turned each later anchor into an
    un-excusable "anchor changed" error — 4 of the 14 real errors on the
    07-18 -> 07-25 transition were position shifts naming an
    unactionable remedy. It also ran the other way: an exercise appended
    at position 9 of an 8-slot session had no counterpart at position 9,
    so every rule skipped it, and appending became the way past all of
    them.

    RECONCILED SUBSTITUTIONS ARE EXEMPT from rules 1b, 2 and 3. When the
    ledger has already recorded that the user performed X where Y was
    prescribed, prescribing X is not a failure to rotate — it is the
    system finally writing down what was happening anyway. Refusing
    ``Rear Delt Fly Machine -> Dumbbell Rear Delt Fly`` as "differs only
    by equipment" while ``pending_reconciliation`` reports that exact
    swap is the system arguing with its own observations.

    Plus the precondition that makes rules 1-4 meaningful: **every anchor
    or rotating slot must be on the catalog**. An off-catalog name has no
    pattern identity, so passing it would make "invent a name" the
    cheapest way through this function.
    """
    if catalog is None:
        catalog = load_pattern_catalog()
    errors: list[str] = []
    notes: list[str] = []
    if not new_block:
        return {"errors": ["block: no proposed block to validate"],
                "notes": [], "boundary": True, "boundary_basis": None,
                "diffable": False, "undiffable_reason": "no proposed block",
                "sessions_matched": {}}

    new_sessions = new_block.get("sessions") or {}
    prev_sessions = (prev_block or {}).get("sessions") or {}
    boundary, basis = _boundary_state(prev_block, new_block)
    undiffable = _is_self_diff(prev_block, new_block)
    if undiffable:
        notes.append(f"block: {undiffable}")

    pairs, new_unmatched, prev_unmatched = _pair_sessions(
        prev_sessions, new_sessions, catalog)

    prev_all: dict[str, str] = {}
    for stype, slots in prev_sessions.items():
        for s in slots:
            key = (s.get("exercise") or "").strip().lower()
            if key:
                prev_all.setdefault(key, stype)
    # What the ledger says actually happened in place of what was
    # prescribed. A movement the user substituted in is not a movement
    # the coach failed to rotate away from.
    reconciled = {(s.get("performed_instead") or "").strip().lower()
                  for slots in prev_sessions.values() for s in slots
                  if s.get("performed_instead")}
    reconciled.discard("")

    for stype in sorted(new_sessions):
        new_slots = new_sessions[stype] or []
        prev_key = pairs.get(stype)
        prev_slots = prev_sessions.get(prev_key) or [] if prev_key else []
        matched = bool(prev_key)

        prev_names = _slot_names(prev_slots)
        prev_patterns = _slot_patterns(prev_slots, catalog)
        prev_history = {h.strip().lower()
                        for s in prev_slots for h in (s.get("history") or [])
                        if h}
        prev_anchors = {(s.get("exercise") or "").strip().lower(): s
                        for s in prev_slots if (s.get("tag") or "") == "anchor"}
        rotating_seen = 0
        pattern_gained = False
        changed_mid_block: list[str] = []

        for i, slot in enumerate(new_slots, start=1):
            pos = int(slot.get("position") or i)
            name = (slot.get("exercise") or "").strip()
            key = name.lower()
            tag = slot.get("tag") or "rotating"
            label = f"block {stype} slot {pos} ({name or '<blank>'})"

            # Precondition — identity must be checkable.
            if tag in SLOT_TAGS and not pattern_group(name, catalog):
                errors.append(
                    f"{label}: not in the exercises catalog, so its movement "
                    f"pattern cannot be verified. Use a catalog name or add "
                    f"the entry first.")
                continue

            pg_new = pattern_group(name, catalog)
            exempt = key in reconciled

            if tag == "rotating" and matched:
                rotating_seen += 1
                if key in prev_names:
                    if boundary:
                        # Rule 1.
                        errors.append(
                            f"{label}: rotating slot is unchanged from the "
                            f"previous block. A rotating slot must change "
                            f"every block — repeating it is how a weekly "
                            f"distribution target gets satisfied forever "
                            f"without rotating anything.")
                elif boundary and not exempt and key in prev_all:
                    # Rule 1b — the reshuffle.
                    errors.append(
                        f"{label}: {name} was in the previous block, in "
                        f"{prev_all[key]}. Moving a movement between sessions "
                        f"is not rotating it — the block trains exactly what "
                        f"it trained last block.")
                elif boundary and not exempt and key in prev_history:
                    # Rule 2.
                    errors.append(
                        f"{label}: returns to {name}, which held a slot in "
                        f"this session within the last "
                        f"{ROTATION_HISTORY_DEPTH} blocks. Cycling between "
                        f"the same few movements is not rotation.")
                elif boundary and not exempt:
                    flavour = next(
                        (p for p in sorted(prev_names)
                         if _equipment_flavour_only(name, p)), None)
                    if flavour is not None:
                        # Rule 3.
                        prev_name = (catalog.get(flavour) or {}).get(
                            "name", flavour)
                        errors.append(
                            f"{label}: {prev_name} -> {name} differs only by "
                            f"equipment. That is not a rotation.")
                if key not in prev_names:
                    changed_mid_block.append(name)
                if pg_new is not None and pg_new not in prev_patterns:
                    pattern_gained = True

            # Rule 6 — rotated-in and at-risk accessory work rides a
            # compound's rest. A compound is exempt: it is the host, not
            # the guest, and a newly introduced anchor press has nothing
            # to ride. "Rotated in" is scoped to THIS session when the
            # session has a counterpart, and falls back to the whole
            # block when it does not.
            rotated_in = bool(name) and (
                key not in prev_names if matched else key not in prev_all)
            is_compound = bool((catalog.get(key) or {}).get("is_compound"))
            if name and not is_compound and (rotated_in or slot.get("at_risk")):
                errors.extend(_superset_errors(stype, slot, pos, name,
                                               new_slots, catalog, label,
                                               rotated_in))

        errors.extend(_host_capacity_errors(stype, new_slots, catalog))

        # Rule 5 — anchors, matched by identity. An anchor that was here
        # last block and is not here now is the change; which ordinal it
        # used to sit at is not a fact about the program.
        new_anchors = {(s.get("exercise") or "").strip().lower(): s
                       for s in new_slots if (s.get("tag") or "") == "anchor"}
        # Only the coach-declarable subset counts as a DECLARATION.
        # ``user_substitution`` is deliberately absent: it is a claim about
        # what the ledger recorded, so it is granted below by
        # `_anchor_change_excuse` reading the ledger, never by a slot
        # asserting it. See COACH_DECLARABLE_ANCHOR_CHANGE_REASONS.
        declared = [s for k, s in sorted(new_anchors.items())
                    if k not in prev_anchors
                    and s.get("anchor_change_reason")
                    in COACH_DECLARABLE_ANCHOR_CHANGE_REASONS]
        new_names_here = _slot_names(new_slots)
        for gone in sorted(k for k in prev_anchors if k not in new_anchors):
            derived = _anchor_change_excuse(prev_anchors[gone], new_names_here)
            prev_name = (catalog.get(gone) or {}).get("name", gone)
            if derived:
                basis = ("the ledger" if derived == "user_substitution"
                         else "the block artifact")
                notes.append(
                    f"block {stype}: anchor changed — {prev_name} dropped on "
                    f"{derived}, derived from {basis}.")
                continue
            if declared:
                declared.pop(0)
                continue
            errors.append(
                f"block {stype}: anchor changed — {prev_name} is no longer in "
                f"this session and nothing qualifies the change. Set "
                f"anchor_change_reason on its replacement (one of "
                f"{', '.join(COACH_DECLARABLE_ANCHOR_CHANGE_REASONS)}), or add "
                f"'— anchor change: injury' under the bullet that replaces it. "
                f"(user_substitution is not declarable: it is granted only "
                f"when the ledger recorded the swap.)")

        # Rule 4 — the session as a whole must gain a pattern.
        if boundary and rotating_seen and not pattern_gained:
            errors.append(
                f"block {stype}: no rotating slot moved to a movement pattern "
                f"this session did not already have. At least one must — "
                f"otherwise every slot can progress a rung inside its own "
                f"category and the categories that are missing stay missing.")
        if not boundary and changed_mid_block:
            notes.append(
                f"block {stype}: {len(changed_mid_block)} rotating slot(s) "
                f"changed mid-block ({', '.join(sorted(changed_mid_block))}). "
                f"Legal — a stall response or a gym-floor substitution is a "
                f"reason to change one — but a whole session's worth is the "
                f"block dissolving.")

    # A split change is a real decision (D7 contemplates four days going
    # to three) and must not be silently exempted the way a renamed
    # heading was. A session SWAPPED for another blocks, because that is
    # what a rename looks like once content matching has failed; a pure
    # addition or a pure reduction is reported and allowed.
    if new_unmatched and prev_unmatched:
        errors.append(
            f"block: session(s) {', '.join(new_unmatched)} do not continue "
            f"any session in the previous block, while "
            f"{', '.join(prev_unmatched)} disappeared. Rotation cannot be "
            f"verified across a session swap. Keep the previous session "
            f"headings, or persist a new block artifact first "
            f"(python3 -m workout_coach.lib.blocks write ...).")
    elif new_unmatched:
        notes.append(
            f"block: session(s) {', '.join(new_unmatched)} are new — no "
            f"previous session to rotate away from, so only the superset and "
            f"catalog rules bind there.")
    elif prev_unmatched:
        notes.append(
            f"block: session(s) {', '.join(prev_unmatched)} were dropped from "
            f"the split.")

    return {
        "errors":            errors,
        "notes":             notes,
        "boundary":          boundary,
        "boundary_basis":    basis,
        "diffable":          undiffable is None,
        "undiffable_reason": undiffable,
        "sessions_matched":  pairs,
    }


def rotation_diff_errors(prev_block: dict | None, new_block: dict | None,
                         catalog: dict | None = None) -> list[str]:
    """Blocking errors for a proposed block against the one it replaces.

    Pure function. No I/O, no clock, no person — ``catalog`` may be
    ``None``, in which case ``load_pattern_catalog()`` is called once.
    Returns a list of human-readable error strings; empty means the
    rotation is legal. Every string names the session type so the caller
    can point at the offending bullet.

    The signature is fixed: this is what ``render_validators``' render
    gate calls. ``rotation_diff_report`` is the same computation with its
    non-blocking findings attached — read that one when you need to know
    WHY the list is empty (mid-block, un-diffable, a session that has no
    predecessor) rather than only that it is.
    """
    return rotation_diff_report(prev_block, new_block, catalog)["errors"]


def _host_capacity_errors(stype, slots, catalog):
    """No compound may be declared the host of more accessories than it
    has rest windows for. Otherwise the superset rule is satisfiable by
    naming one squat on every accessory bullet in the session."""
    counts: dict[str, int] = {}
    for s in slots:
        host = (s.get("superset_with") or "").strip().lower()
        if host:
            counts[host] = counts.get(host, 0) + 1
    out = []
    for host, n in sorted(counts.items()):
        if n > SUPERSET_HOST_CAPACITY:
            name = (catalog.get(host) or {}).get("name", host)
            out.append(
                f"block {stype}: {n} accessories are supersetted onto {name}, "
                f"which has room for {SUPERSET_HOST_CAPACITY}. Spread them "
                f"across the session's compounds or cut a slot.")
    return out


def _superset_errors(stype, slot, pos, name, new_slots, catalog, label,
                     rotated_in=True):
    """Rule 6's body: non-compound work must ride a compound's rest.

    Not a position rule. Moving the laggards out of the tail was tried on
    2026-07-25 and they were dropped at positions 4 and 5 of 8 anyway;
    what gets dropped is isolation work, wherever it sits. A set that
    happens inside another exercise's rest period costs no extra session
    minutes, which is the only lever that has not been pulled yet.
    """
    host_name = (slot.get("superset_with") or "").strip()
    if not host_name:
        # An unresolved hint is NOT a missing pairing. Saying "left
        # standalone" when the plan wrote the pairing sends the coach to
        # add a note that is already there; the actionable fact is that
        # the words did not name a slot in this session.
        unresolved = (slot.get("superset_hint_unresolved") or "").strip()
        if unresolved:
            return [f"{label}: a superset host was written ({unresolved!r}) "
                    f"but it does not resolve to any exercise in this "
                    f"session. Name the host's catalog exercise, e.g. "
                    f"'superset with the barbell back squat above'."]
        why = ("rotated in this block but left standalone"
               if rotated_in else
               "keeps going unperformed and is still standalone")
        return [f"{label}: {why}. Superset it onto a compound earlier in the "
                f"session (set superset_with) so the set happens inside that "
                f"exercise's rest period."]
    host = None
    for other in new_slots:
        if (other.get("exercise") or "").strip().lower() == host_name.lower():
            host = other
            break
    if host is None:
        return [f"{label}: superset_with names {host_name}, which is not in "
                f"this session."]
    meta = (catalog or {}).get(host_name.lower()) or {}
    out = []
    if not meta.get("is_compound"):
        out.append(f"{label}: superset host {host_name} is not a compound. "
                   f"Pair rotated-in work with a compound, whose rest period "
                   f"is long enough to absorb it.")
    if int(host.get("position") or 0) >= pos:
        out.append(f"{label}: superset host {host_name} is at position "
                   f"{host.get('position')}, not earlier in the session. The "
                   f"host has to come first for the rest period to exist.")
    return out


# ------------------------------------------- the artifact against the spec
#
# R-05. The block artifact ships beside `core_week_spec` and contradicts
# it. Measured on the live payload, both people, 2026-08-02:
#
#     lower_a core: [Ab Crunch Machine]    upper_a core: [Ab Crunch Machine]
#     lower_b core: [Cable Reverse Crunch] upper_b core: [Ab Crunch Machine]
#     distinct core exercises: 2   (spec floor 3)
#     Ab Crunch Machine in 3 sessions      (spec cap 2)
#     one benched movement still holding a slot
#
# SKILL.md tells the coach an in-flight block outranks the
# frequency-derived split, which reads as "copy the slots" — and copying
# them fails the gate on several counts. The block descends from the
# pre-spec era: it was derived from a plan written before these axes
# existed.
#
# TWO DEFECTS, TWO DIFFERENT ANSWERS, and the difference is provenance.
#
# THE CORE AXES GET A MARKER, NOT A REWRITE. The block is a RECORD of
# what was prescribed, and it is the basis every rotation check differs
# the next generation against. Reconciling it into compliance means
# inventing core slots nobody prescribed, and then generation N+1 is
# compared against a block that was never written and never trained —
# precisely the drift `reconcile_block_with_logs` exists to undo, run in
# reverse. There is also nothing to reconcile FROM: the spec states
# floors, not a selection, so "make it comply" has no unique answer and
# the data layer has no authority to pick one. So the artifact keeps
# saying what happened, and it carries a computed, machine-readable
# statement of exactly which axes copying it would violate. The marker is
# DERIVED — catalog plus spec, neither of them coach-written — so it
# cannot be turned off by anything the coach writes.
#
# THE BENCHED SLOT GETS DELETED. That one is not a record of a
# prescription worth keeping: `adherence.benched` is the ledger's finding
# that the user does not perform this movement, and the payload's own
# instruction is "must not re-prescribe". Leaving it in a slot the coach
# is told to copy is the artifact contradicting the ledger. The same
# defect was already closed one surface over — `read_tracker` excludes
# benched movements from `rotation_candidates` for this exact reason —
# and this is the other half of it. See `strip_benched_slots`.
def core_spec_conflicts(block: dict | None, catalog: dict | None = None,
                        spec: dict | None = None,
                        db: dict | None = None) -> dict | None:
    """Which `core_week_spec` axes this block's own core slots violate.

    ``None`` when there is no block. Otherwise a dict the payload carries
    verbatim::

        {"spec": "core_week_spec",
         "compliant": bool,
         "copy_core_slots": bool,      # the directive, in one boolean
         "conflicts": [{axis, observed, required, detail}, ...],
         "core_slots": {session_type: [exercise, ...]},
         "axes_checked": [...], "axes_not_checked": [...],
         "directive": "<one sentence for the coach>"}

    ``copy_core_slots`` is the field a consumer should branch on. False
    means the block's core selection predates the current spec and
    copying it forward reproduces a rejected plan; the coach must derive
    the week's core work from `core_week_spec` and treat the block as
    authoritative only for its NON-core slots.

    WHAT IS CHECKED, and what deliberately is not. Four axes are
    answerable from an artifact plus the catalog:

      * ``sets_per_session`` — per session, using the CONTENT-derived
        session type (`adherence.session_type_from_title` with the
        block's own slots), never the stored heading claim. A session
        whose type cannot be determined, or whose core slots carry no
        recorded dose, is skipped rather than reported: this marker is
        read by a coach, and a fabricated conflict tells it not to copy a
        block that was fine.
      * ``min_distinct_exercises_per_week``
      * ``max_sessions_per_exercise_per_week``
      * ``min_pattern_categories_per_week`` — the catalog's own CORE
        ``### Subsection`` headings, read through ``pattern_group``.

    The three flexion axes (``min_flexion_sets_per_week``,
    ``min_flexion_share_of_core_sets``,
    ``min_loaded_flexion_exercises_per_week``) are NOT checked here, and
    that is a rule about this repo rather than about the data: the
    combined requirement is one formula and it already has one
    implementation, in `render_validators`. A second copy is how the two
    end up disagreeing about the number that decides a render. They are
    named in ``axes_not_checked`` so ``compliant: True`` reads as
    "compliant on the axes an artifact can answer", never as "checked
    everything".
    """
    sessions = (block or {}).get("sessions") or {}
    if not sessions:
        return None
    if catalog is None:
        catalog = load_pattern_catalog(db)
    if spec is None:
        spec = CORE_WEEK_SPEC

    def _axis(key):
        val = spec.get(key)
        return CORE_WEEK_SPEC[key] if val is None else val

    per_session = _axis("sets_per_session") or {}
    lower_dose = per_session.get("lower", CORE_WEEK_SPEC["sets_per_session"]["lower"])
    upper_dose = per_session.get("upper", CORE_WEEK_SPEC["sets_per_session"]["upper"])
    tol = _axis("session_set_overshoot_tolerance")
    stored_types = (block or {}).get("session_types") or {}

    core_slots: dict[str, list[str]] = {}
    sessions_per_exercise: dict[str, set[str]] = {}
    categories: set[str] = set()
    conflicts: list[dict] = []
    undetermined: list[str] = []

    for stype in sorted(sessions):
        slots = sessions[stype] or []
        core = [s for s in slots
                if ((catalog.get((s.get("exercise") or "").strip().lower())
                     or {}).get("muscle") == "CORE")]
        core_slots[stype] = [s.get("exercise") for s in core]
        for s in core:
            name = (s.get("exercise") or "").strip()
            sessions_per_exercise.setdefault(name, set()).add(stype)
            pg = pattern_group(name, catalog)
            if pg:
                categories.add(pg)

        kind = session_type_from_content(slots, db) or stored_types.get(stype)
        if kind is None:
            undetermined.append(stype)
            continue
        floor = (upper_dose if kind == "upper" else max(lower_dose, upper_dose))
        doses = [(s.get("dose") or {}).get("prescribed_sets") for s in core]
        if core and all(d is None for d in doses):
            undetermined.append(stype)
            continue
        sets = sum(int(d) for d in doses if isinstance(d, (int, float))
                   and not isinstance(d, bool))
        if sets < floor:
            conflicts.append({
                "axis":     "sets_per_session",
                "session":  stype,
                "observed": sets,
                "required": floor,
                "detail":   (f"{stype} is a {kind} session and carries {sets} "
                             f"core set(s); the spec budgets {floor}-"
                             f"{floor + tol}"),
            })
        elif sets > floor + tol:
            conflicts.append({
                "axis":     "sets_per_session",
                "session":  stype,
                "observed": sets,
                "required": floor + tol,
                "detail":   (f"{stype} is a {kind} session and carries {sets} "
                             f"core set(s); the spec budgets {floor}-"
                             f"{floor + tol}"),
            })

    distinct_floor = _axis("min_distinct_exercises_per_week")
    if len(sessions_per_exercise) < distinct_floor:
        conflicts.append({
            "axis":     "min_distinct_exercises_per_week",
            "observed": len(sessions_per_exercise),
            "required": distinct_floor,
            "detail":   (f"the block holds {len(sessions_per_exercise)} distinct "
                         f"core exercise(s) across the week "
                         f"({', '.join(sorted(sessions_per_exercise)) or 'none'}); "
                         f"the spec requires {distinct_floor}"),
        })

    cap = _axis("max_sessions_per_exercise_per_week")
    for name, where in sorted(sessions_per_exercise.items()):
        if len(where) > cap:
            conflicts.append({
                "axis":     "max_sessions_per_exercise_per_week",
                "exercise": name,
                "observed": len(where),
                "required": cap,
                "detail":   (f"{name} holds a slot in {len(where)} sessions "
                             f"({', '.join(sorted(where))}); the spec caps one "
                             f"core exercise at {cap} sessions a week"),
            })

    cat_floor = _axis("min_pattern_categories_per_week")
    if categories and len(categories) < cat_floor:
        conflicts.append({
            "axis":     "min_pattern_categories_per_week",
            "observed": len(categories),
            "required": cat_floor,
            "detail":   (f"the block's core slots span {len(categories)} pattern "
                         f"categor(ies) ({', '.join(sorted(categories))}); the "
                         f"spec requires {cat_floor}"),
        })

    compliant = not conflicts
    return {
        "spec":             "core_week_spec",
        "compliant":        compliant,
        "copy_core_slots":  compliant,
        "conflicts":        conflicts,
        "core_slots":       core_slots,
        "sessions_undetermined": sorted(set(undetermined)) or None,
        "axes_checked": [
            "sets_per_session", "min_distinct_exercises_per_week",
            "max_sessions_per_exercise_per_week",
            "min_pattern_categories_per_week",
        ],
        # Named, not silently omitted: `compliant` must never read as
        # "every axis was checked". See the docstring for why these three
        # live in `render_validators` and only there.
        "axes_not_checked": [
            "min_flexion_sets_per_week", "min_flexion_share_of_core_sets",
            "min_loaded_flexion_exercises_per_week",
        ],
        "directive": (
            "This block's core slots satisfy every core_week_spec axis an "
            "artifact can answer; they may be carried forward."
            if compliant else
            "This block predates the current core_week_spec and its core "
            "slots violate it. DO NOT COPY THEM. Build the week's core work "
            "from core_week_spec and treat the block as authoritative for "
            "its non-core slots only."),
    }


def strip_benched_slots(block: dict | None, benched) -> tuple[dict | None, list]:
    """Remove benched movements from every block slot. ``(block, removed)``.

    A benched movement must never survive in a block slot. The bench list
    is the LEDGER's finding — two consecutive prescriptions into sessions
    that were trained, performed neither time — and the payload's
    instruction on it is "must not re-prescribe". An artifact the coach is
    told outranks the split, still holding that movement in a slot, is the
    data layer handing over a prescription its own ledger has withdrawn.

    Deleted rather than flagged, and the asymmetry with `core_spec_conflicts`
    is deliberate. There the spec states a floor with many legal answers
    and the artifact is the only record of which one was prescribed, so
    rewriting it would invent history. Here the answer is unique and it is
    "not this one" — removing the slot destroys no information the ledger
    does not already hold, and every removal comes back in the returned
    list so it is reported rather than silently disappeared.

    ``benched`` may be the ``adherence["benched"]`` entries or a bare
    iterable of names. ``bench_blocked`` entries must NOT be passed: those
    are movements the route guard REFUSED to bench because they are the
    last way into a muscle, and the coach is expected to keep prescribing
    them.

    Positions are left as they are. They came from counting bullets in the
    plan this block was derived from, and renumbering them would make a
    removal look like a reshuffle to the next generation's diff.
    """
    names = set()
    for b in benched or []:
        name = b.get("exercise") if isinstance(b, dict) else b
        if name:
            names.add(str(name).strip().lower())
    if not block or not names:
        return block, []
    out = json.loads(json.dumps(block))
    removed: list[dict] = []
    for stype, slots in (out.get("sessions") or {}).items():
        keep = []
        for s in slots or []:
            if (s.get("exercise") or "").strip().lower() in names:
                removed.append({
                    "session_type": stype,
                    "position":     s.get("position"),
                    "exercise":     s.get("exercise"),
                    "tag":          s.get("tag"),
                    "reason":       "benched",
                })
                continue
            keep.append(s)
        out["sessions"][stype] = keep
    return out, removed


# --------------------------------------------------------- reconciliation
def reconcile_block_with_logs(block: dict | None, rows: list[dict], db: dict,
                              catalog: dict | None, start: date,
                              end: date) -> tuple[dict | None, list[dict]]:
    """Fold gym-floor substitutions back into the block artifact.

    Run at the boundary. A slot whose exercise was never logged in the
    block's window, while a DIFFERENT movement of the same pattern group
    was, records what actually happened: the slot's exercise is rewritten
    to the performed movement and ``substituted_from`` remembers the
    original.

    Without this the artifact drifts away from reality and every
    subsequent rotation check compares the new plan against a block that
    was never trained. Returns ``(block_or_None, changes)``; the input is
    not mutated.
    """
    if not block:
        return None, []
    if catalog is None:
        catalog = load_pattern_catalog(db)
    performed: dict[str, int] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        d = _parse_iso_date(r.get("date"))
        if d is None or d < start or d >= end:
            continue
        key = (r.get("exercise") or "").strip().lower()
        entry = db.get(key) or {}
        if entry.get("is_warmup") or entry.get("is_cardio"):
            continue
        performed[key] = performed.get(key, 0) + 1

    planned = {(s.get("exercise") or "").strip().lower()
               for slots in (block.get("sessions") or {}).values() for s in slots}
    extras = {k: v for k, v in performed.items() if k not in planned}

    out = json.loads(json.dumps(block))
    changes: list[dict] = []
    claimed: set[str] = set()
    for stype, slots in (out.get("sessions") or {}).items():
        for slot in slots:
            key = (slot.get("exercise") or "").strip().lower()
            if performed.get(key):
                continue
            pg = pattern_group(key, catalog)
            if pg is None:
                continue
            cand = next(
                (k for k in sorted(extras, key=lambda k: (-extras[k], k))
                 if k not in claimed and pattern_group(k, catalog) == pg),
                None)
            if cand is None:
                continue
            claimed.add(cand)
            changes.append({
                "session_type": stype,
                "position":     slot.get("position"),
                "planned":      slot.get("exercise"),
                "performed":    (catalog.get(cand) or {}).get("name", cand),
                "pattern":      pg,
                "sets":         extras[cand],
            })
            slot["substituted_from"] = slot.get("exercise")
            slot["exercise"] = (catalog.get(cand) or {}).get("name", cand)
    return out, changes


# ------------------------------------------------------------ cold start
# Transfer coefficients between equipment classes at a matched rep count.
# Only the pairs where the difference is structural are listed; anything
# absent is 1.0 (same movement, comparable loading). The dumbbell numbers
# are TOTAL load across both hands, which is how this tracker logs them
# (a 52kg dumbbell bench press is 26 per hand).
#
# These are working coefficients for choosing a FIRST session's weight,
# not measurements. They are deliberately conservative in the direction
# that matters: getting a first exposure 10% light costs one session,
# getting it 10% heavy costs a form breakdown on an unfamiliar pattern.
_EQUIP_TRANSFER = {
    ("BB", "DB"):      0.80,
    ("DB", "BB"):      1.15,
    ("Machine", "BB"): 0.75,
    ("Machine", "DB"): 0.65,
    ("Cable", "DB"):   0.85,
    ("Cable", "BB"):   0.95,
    ("BB", "Machine"): 1.20,
    ("DB", "Machine"): 1.35,
    ("DB", "Cable"):   1.10,
    ("BB", "Cable"):   1.05,
}

# First exposure to an unfamiliar movement is limited by coordination,
# not by the muscle. The catalog's own guidance for a new movement is
# "leave 2-3 in the tank"; 2-3 RIR against a rep-matched load is
# ~10-15% off, so the derived number is discounted accordingly.
NOVELTY_DISCOUNT = 0.85

# LATERALITY. One limb does not lift what two limbs lift. This tracker
# logs bilateral dumbbell work as the TOTAL across both hands, and it
# logs a per-side prescription per side ("16kgx8-10 per side"), so a
# single-limb candidate derived from a bilateral reference has to be
# taken down to one limb's share before anything else.
#
# 0.5 is the per-limb share and no more. The bilateral deficit means a
# trained lifter's single-limb maximum is often slightly ABOVE half the
# two-limb figure, so 0.5 is the conservative end of the observed range —
# and a first exposure to a single-limb movement is limited by frontal-
# plane stability rather than by the prime mover anyway. The reverse
# direction (a bilateral candidate off a unilateral reference) would
# require multiplying UP, which is never done: it is suppressed instead.
UNILATERAL_FROM_BILATERAL = 0.5

# Name tokens that mark a movement as single-limb. The catalog carries no
# laterality field, so this reads the names it does carry. The ``-tion``
# forms are deliberate and load-bearing: ``Cable Hip Abduction`` is one
# leg at a time while ``Hip Abductor Machine`` drives both against pads,
# and the catalog spells those two differently.
# ``tests/test_w5_safety.py`` pins the classification of every catalog
# entry this currently decides, in both directions, so a future entry
# that breaks the heuristic fails a test instead of shipping a doubled
# load.
_UNILATERAL_TOKENS = frozenset({
    "single", "unilateral", "suitcase", "kickback", "split", "bulgarian",
    "lunge", "pistol", "concentration", "abduction", "adduction",
})
# "one arm row" / "one leg" — only when followed by a limb word, because
# "one" alone is a number.
_ONE_LIMB_RE = re.compile(r"\bone[\s-]+(arm|leg|side|hand)\b", re.IGNORECASE)

# A FREE-WEIGHT compound whose loading nobody has measured for this
# person gets a ceiling, not a point estimate. Inside one pattern group
# two compounds can differ by a factor of two — a Barbell Good Morning is
# conventionally loaded at 30-50% of a Romanian Deadlift, a front squat
# at 80-85% of a back squat — and both pairs share a pattern group AND an
# equipment class, so nothing in the catalog separates them. The cap sits
# at the bottom of that observed spread because the failure modes are not
# symmetric: a light first session costs a session, a heavy first session
# on an unfamiliar hinge costs a back. The uncapped derivation put an
# 80kg x 10 good morning up as a FIRST exposure against a rep-matched
# reference of 95kg — a heavier hinge than the reference itself would be
# worked at, on a movement conventionally loaded at a third of it.
NOVEL_COMPOUND_CAP = 0.50

# ...and only there. Three conditions, each doing separate work.
#
# FREE WEIGHT. On a guided path the variants inside one pattern group are
# the same pin stack pulled at a different angle and they load
# comparably; a close-grip pulldown is not half a wide-grip pulldown.
# Free weights are where the intra-family spread lives, and they are also
# where a mis-derived first set fails as a joint rather than as a missed
# rep.
_FREE_WEIGHT = frozenset({"BB", "DB", "Smith", "LM", "KB", "Plate"})
# AXIALLY LOADED. Both halves of the argument point at hinges and squats
# and at nothing else. The spread is theirs — a good morning sits at
# 30-50% of an RDL while an incline press sits at 85-90% of a flat press
# — and so is the injury: you rack or dump a failed press, you do not
# rack a failed hinge. Capping every free-weight compound put a 22kg
# dumbbell incline press in front of someone flat-pressing 52, which is
# a wasted session bought with no safety at all.
_AXIAL_TOKENS = frozenset({"hinge", "squat", "deadlift"})
# NOTHING HAS ALREADY MOVED THE LOAD DOWN. An equipment coefficient below
# 1.0 IS the conservative adjustment for that pair (Machine -> BB is 0.75
# precisely because the barbell version is less supported); stacking a
# 0.50 cap on top double-discounts and produces an empty bar. A
# coefficient above 1.0 moves the load UP on a movement the person has
# never performed, which is exactly when a ceiling should bite.

# Load granularity per equipment class, in kg. Rounding to the increment
# the gym actually has is what stops the coach writing "43.7kg".
_INCREMENT = {"BB": 2.5, "DB": 2.0, "Machine": 5.0, "Cable": 2.5,
              "Smith": 2.5, "Plate": 1.25, "LM": 2.5}
_DEFAULT_INCREMENT = 2.5

# You cannot load a barbell below its own mass. Not a coefficient — a
# physical floor — so it is applied after the arithmetic and labelled as
# what it is rather than folded into ``transfer``. Only the Olympic bar
# is listed: Smith and landmine bars run anywhere from 7 to 25 kg and
# asserting one number for them would be a guess. Without this the
# conservative chain produced "Romanian Deadlift: 15kg", which is five
# kilos less than the empty bar.
_BAR_MASS_KG = {"BB": 20.0}


def _round_to(value: float, step: float) -> float:
    if step <= 0:
        return round(value, 1)
    return round(round(value / step) * step, 2)


def is_unilateral(exercise: str) -> bool:
    """True when ``exercise`` is loaded one limb at a time.

    Read off the name, because the catalog has no laterality column. See
    ``_UNILATERAL_TOKENS`` for the rule and
    ``tests/test_w5_safety.py::LateralityTests`` for the pinned
    classifications. A catalog field would be better and is the right
    follow-up; until then this is the only signal there is, and getting
    it wrong in the permissive direction doubles a starting load.
    """
    words = _identity_words(exercise) | {
        w for w in _WORD_RE.findall((exercise or "").lower())}
    if words & _UNILATERAL_TOKENS:
        return True
    return bool(_ONE_LIMB_RE.search(exercise or ""))


def derived_starting_load(exercise: str, e1rm: dict, catalog: dict,
                          db: dict | None = None,
                          target_reps: int = 10) -> dict | None:
    """A legal starting weight for a movement with no logged history.

    THE REASON THIS EXISTS. The payload names only the ~46 exercises the
    person has logged, and the active load rule is "copy last session's
    load forward" — which has been active on every run, because recovery
    has landed in the 4-6.5 band every time. Between them there is no
    legal way to write a weight for anything else, so rotating a new
    movement in is not merely discouraged, it is impossible. Novelty
    needs a number.

    THE DERIVATION.

    1. **Sibling pool** — catalog entries sharing the candidate's
       ``pattern_group``. Same muscle, same movement pattern: the closest
       thing to a like-for-like transfer the catalog can express.
    2. **Reference** — of those siblings, the one with logged history and
       the most recent ``last_date``; ties break on the higher e1RM. Most
       recent, because that is the load the person is currently adapted
       to, not the one they were strongest at.
    3. **Rep-matched base** — invert Epley at the target rep count:
       ``base = e1RM / (1 + reps/30)``. Comparing at matched reps is the
       point; comparing e1RMs across a rep-range change is how a 15-rep
       machine movement becomes a 5-rep barbell prescription.
    4. **Equipment transfer** — ``_EQUIP_TRANSFER`` for the
       reference-to-candidate equipment pair.
    5. **Laterality transfer** — ``UNILATERAL_FROM_BILATERAL`` when the
       candidate is single-limb and the reference is not.
    6. **Compound cap** — ``NOVEL_COMPOUND_CAP`` when the candidate is a
       compound, because two compounds in one pattern group can differ by
       a factor of two and the catalog cannot say which.
    7. **Novelty discount** — ``NOVELTY_DISCOUNT`` (0.85), first exposure
       being coordination-limited.
    8. **Round** to the candidate equipment's increment.

    WHEN NO NUMBER IS OFFERED, AND WHY THAT IS THE ANSWER. ``load_kg`` is
    ``None`` in three cases, each carrying a ``load_basis`` that says
    which:

      ``bodyweight``        the movement has no external load at all.
      ``no_reference``      no sibling has history — the pre-existing
                            ``None`` return, now expressed as a basis so
                            ``rotation_candidates`` can still offer the
                            movement without a weight.
      ``unknown_transfer``  a sibling exists, but the equipment classes
                            differ and no coefficient covers the pair.
                            There is nothing to base a number on, so
                            there is no number.

    That last one is the fix for the shipped bug. ``transfer`` defaulted
    to 1.0 for any pair missing from the table and the confidence band
    then read ``transfer != 1.0`` as the uncertain case — so the LESS the
    model adjusted, the MORE confident it claimed to be, and a defaulted
    coefficient shipped as ``medium``. The two ways to reach 1.0 are now
    distinguished: same equipment class is a FACT about the pair
    (``like_for_like``), a missing coefficient is IGNORANCE
    (``unknown_transfer``), and ignorance produces no figure. A missing
    suggestion costs a conservative first session; a confident wrong one
    costs an injury.

    ``confidence`` bands what IS offered: ``medium`` for a like-for-like
    derivation, ``low`` once any coefficient or cap has been applied,
    ``none`` when no load is offered, ``n/a`` for bodyweight.

    Returns ``None`` only for an off-catalog name. "No sibling with
    history" now comes back as an entry with ``load_kg: None`` and
    ``load_basis: "no_reference"``, because dropping the movement
    entirely is what closed the novelty channel for exactly the patterns
    the priority tiers mark ``emphasis`` — the ones at zero precisely
    because they are the gap.

    The returned entry is deliberately terse. The prose statement of the
    rule belongs once, in ``rotation_candidates``'s ``derivation`` header
    and in this docstring, not repeated on every one of ~50 candidates.
    """
    key = (exercise or "").strip().lower()
    meta = (catalog or {}).get(key)
    if meta is None:
        return None
    pg = meta["pattern"]
    name_out = meta["name"]
    equip = (meta.get("equipment") or "").strip() or None

    def _blank(basis: str, unit=None, **extra) -> dict:
        return {"exercise": name_out, "pattern": pg, "load_kg": None,
                "unit": unit, "target_reps": target_reps, "ref": None,
                "load_basis": basis,
                "confidence": "n/a" if basis == "bodyweight" else "none",
                **extra}

    if equip in ("BW",):
        return _blank("bodyweight", unit="bodyweight")

    e1rm_lower = {k.strip().lower(): (k, v) for k, v in (e1rm or {}).items()}
    best = None
    for sib_key, sib in (catalog or {}).items():
        if sib_key == key or sib["pattern"] != pg:
            continue
        hit = e1rm_lower.get(sib_key)
        if not hit:
            continue
        name, block = hit
        val = block.get("current_e1rm_kg")
        last = block.get("last_date")
        if not val or not last:
            continue
        cand = (last, float(val), name, sib.get("equipment"))
        if best is None or cand[:2] > best[:2]:
            best = cand
    if best is None:
        return _blank("no_reference")
    last_date, ref_e1rm, ref_name, ref_equip = best

    ref_meta = {"ref": ref_name, "ref_e1rm_kg": round(ref_e1rm, 1),
                "ref_last": last_date}

    # Equipment. Same class is a fact; a listed pair is a stated
    # coefficient; anything else is ignorance and stops here.
    if ref_equip == equip:
        equip_transfer, basis = 1.0, "like_for_like"
    elif (ref_equip, equip) in _EQUIP_TRANSFER:
        equip_transfer = _EQUIP_TRANSFER[(ref_equip, equip)]
        basis = "equipment_coefficient"
    else:
        return _blank("unknown_transfer", **ref_meta,
                      note=(f"no transfer coefficient from {ref_equip} to "
                            f"{equip}; start at a load controllable for "
                            f"{target_reps} reps and log it"))

    # Laterality. Down to one limb's share, never up to two.
    lateral = 1.0
    cand_uni, ref_uni = is_unilateral(name_out), is_unilateral(ref_name)
    if cand_uni and not ref_uni:
        lateral = UNILATERAL_FROM_BILATERAL
        basis = "unilateral_from_bilateral"
    elif ref_uni and not cand_uni:
        return _blank("unknown_transfer", **ref_meta,
                      note=(f"{ref_name} is loaded one limb at a time and "
                            f"{name_out} is not; scaling a per-limb load up "
                            f"to a two-limb one is not a derivation"))

    # The movement-level unknown. Two axially loaded compounds in one
    # pattern group can sit a factor of two apart and nothing in the
    # catalog says so. The last test is on the transfer SO FAR, equipment
    # and laterality together: either of those below 1.0 has already
    # moved the load down for this pair, and stacking a 0.50 ceiling on
    # top of them double-discounts — it turned a single-leg RDL into
    # three kilos a hand.
    axial = bool(_AXIAL_TOKENS & set(
        _WORD_RE.findall((meta.get("section") or "").lower())))
    axial = axial or bool(_AXIAL_TOKENS & _identity_words(name_out))
    cap = 1.0
    if (meta.get("is_compound") and equip in _FREE_WEIGHT and axial
            and equip_transfer * lateral >= 1.0):
        cap = NOVEL_COMPOUND_CAP
        if basis == "like_for_like":
            basis = "compound_capped"

    base = ref_e1rm / (1.0 + target_reps / 30.0)
    raw = base * equip_transfer * lateral * cap * NOVELTY_DISCOUNT
    load = _round_to(raw, _INCREMENT.get(equip, _DEFAULT_INCREMENT))
    bar = _BAR_MASS_KG.get(equip)
    if bar is not None and load < bar:
        load, basis = bar, "bar_mass_floor"
    return {
        "exercise":    name_out,
        "pattern":     pg,
        "load_kg":     load,
        "unit":        "kg",
        "target_reps": target_reps,
        **ref_meta,
        "transfer":    round(equip_transfer * lateral * cap, 4),
        "load_basis":  basis,
        # ``medium`` only for a derivation that assumed nothing: same
        # equipment class, same laterality, isolation work whose
        # in-family loads really are comparable. Everything else rests on
        # a coefficient or a cap.
        "confidence":  "medium" if basis == "like_for_like" else "low",
    }


# How many never-performed siblings to offer per pattern group. Three is
# enough to give the coach a real choice without turning the payload into
# a copy of the catalog.
ROTATION_CANDIDATES_PER_PATTERN = 3
# Only patterns the person has trained inside this window are offered.
# Deriving a bench-press weight from a squat the person last did in
# February is not a derivation, it is a guess with arithmetic on top.
ROTATION_CANDIDATE_WINDOW_DAYS = 56
# The rep count every candidate load is derived AT. Ten is the middle of
# the hypertrophy range this coach prescribes in and the rep count a
# first exposure should be learned at — heavy triples on an unfamiliar
# pattern are how a rotation becomes an injury.
ROTATION_CANDIDATE_TARGET_REPS = 10

# How a candidate earns one of the ``per_pattern`` slots. Lower sorts
# first. The list used to be ``sorted(catalog.items())[:3]`` — the first
# three ALPHABETICALLY, which is the same defect class as the stale
# ``stale_exercises`` sort this workstream was created to fix: a slice of
# an arbitrary order reads as a ranking and is not one. Of the four
# entries W6a added, only Ab Wheel Rollout reached the payload and
# Hanging Knee Raise was cut by the letter H.
#
# Three axes, in order.
#
# 1. HOW MUCH THE NUMBER ASSUMED. An entry the coach can price beats one
#    it cannot, and a price resting on nothing beats a price resting on a
#    coefficient. Bodyweight sits in the top band with ``like_for_like``:
#    there is no load to get wrong.
_LOAD_BASIS_RANK = {
    "bodyweight":               0,
    "like_for_like":            0,
    "equipment_coefficient":    1,
    "unilateral_from_bilateral": 1,
    "compound_capped":          1,
    "bar_mass_floor":           1,
    "no_reference":             2,
    "unknown_transfer":         2,
}
# 2. HOW CLOSE IT SITS TO WORK THE PERSON ALREADY DOES, by shared
#    identity words with a logged movement in the same pattern
#    (``Hanging Leg Raise`` -> ``Hanging Knee Raise``). The measured
#    failure of rotated-in work is that it goes unperformed — 28% drop
#    rate against 11% — so the nearest usable neighbour is the one most
#    likely to actually happen, and it is also the one the coach can cue
#    in one sub-bullet. Alphabetical order, which this replaces, carried
#    no information at all: it put Ab Wheel Rollout in the payload and
#    cut Hanging Knee Raise on the letter H.
# 3. Reference freshness, then the name, purely so the order is stable.

# At most this many of one pattern's offers may share an equipment class.
# Five bodyweight entries in QUADS/Squat Pattern otherwise took all three
# slots and hid the only barbell option in the group.
def _max_per_equipment(per_pattern: int) -> int:
    return max(1, (per_pattern + 1) // 2)


def _affinity(name: str, logged_names: set[str]) -> float:
    """Best identity-word overlap between ``name`` and anything logged."""
    want = _identity_words(name)
    if not want:
        return 0.0
    best = 0.0
    for other in logged_names:
        have = _identity_words(other)
        if not have:
            continue
        best = max(best, len(want & have) / len(want | have))
    return best


def _candidate_rank(cand: dict, logged_by_pattern: dict) -> tuple:
    """Sort key for one candidate. See the three axes above."""
    logged = logged_by_pattern.get(cand["pattern"], set())
    return (_LOAD_BASIS_RANK.get(cand.get("load_basis"), 2),
            -_affinity(cand["exercise"], logged),
            # A fresher reference is a better anchor. Descending, so the
            # date string is compared by its complement.
            "" if not cand.get("ref_last") else
            "".join(chr(0x10FFFF - ord(c)) for c in cand["ref_last"]),
            cand["exercise"])


def _pick_per_pattern(cands: list[dict], per_pattern: int,
                      logged_by_pattern: dict, catalog: dict) -> list[dict]:
    """The ``per_pattern`` best offers for one pattern group."""
    ranked = sorted(cands, key=lambda c: _candidate_rank(c, logged_by_pattern))
    quota = _max_per_equipment(per_pattern)
    used: dict[str, int] = {}
    picked: list[dict] = []
    for cand in ranked:
        if len(picked) >= per_pattern:
            break
        equip = (catalog.get(cand["exercise"].lower()) or {}).get("equipment")
        if used.get(equip, 0) >= quota:
            continue
        used[equip] = used.get(equip, 0) + 1
        picked.append(cand)
    # A pattern with only one equipment class still fills its slots.
    for cand in ranked:
        if len(picked) >= per_pattern:
            break
        if cand not in picked:
            picked.append(cand)
    return picked


def rotation_candidates(rows: list[dict], db: dict, catalog: dict,
                        e1rm: dict, today_d: date,
                        per_pattern: int = ROTATION_CANDIDATES_PER_PATTERN,
                        window_days: int = ROTATION_CANDIDATE_WINDOW_DAYS,
                        exclude: set | None = None,
                        priority_tiers: dict | None = None) -> dict:
    """Never-performed catalog movements the coach can legally prescribe.

    Scoped to pattern groups the person trained in the last
    ``window_days`` — those have a reference load to derive from —
    **plus** every pattern belonging to a muscle the priority tiers mark
    ``emphasis``, whether or not it has been trained.

    That second clause is the point. The window gate excluded exactly the
    categories the weekly spec forces the coach to add: for both people
    ``CORE/Anti-Rotation``, ``CORE/Anti-Lateral-Flexion`` and
    ``CORE/Rotation`` offered ZERO candidates, and those are the three
    ``min_pattern_categories_per_week`` demands and the ones the bench
    guard names as stranded. A pattern is at zero because it is the gap,
    so gating novelty on recent work in it closed the only channel that
    could fill it. Emphasis patterns come through with whatever load
    basis is honest, ``load_kg: None`` included — SKILL.md makes
    ``candidates[].load_kg`` the only legal source of a starting weight,
    so a movement missing from this list is a movement the coach has to
    invent a dose for.

    ``exclude`` drops movements the coach must not prescribe — the D5
    bench list. Without it the payload contradicted itself, naming
    ``Leg Curl (Lying)`` in ``adherence.benched`` ("must not
    re-prescribe") and offering it here at a derived 45.0 kg.

    Returns a block whose ``derivation`` states the rule once and whose
    ``candidates`` carry only the numbers. Repeating the rule per entry
    cost 23 KB — a fifth of the whole payload — to say the same sentence
    fifty times.
    """
    cutoff = today_d - timedelta(days=max(window_days - 1, 0))
    banned = {(n or "").strip().lower() for n in (exclude or set())}
    banned.discard("")
    active: set[str] = set()
    ever_logged: set[str] = set()
    logged_by_pattern: dict[str, set[str]] = {}
    for r in rows:
        if not _is_working_set(r):
            continue
        key = (r.get("exercise") or "").strip().lower()
        meta = catalog.get(key)
        if meta is None or meta.get("is_warmup") or meta.get("is_cardio"):
            continue
        ever_logged.add(key)
        logged_by_pattern.setdefault(meta["pattern"], set()).add(meta["name"])
        d = _parse_iso_date(r.get("date"))
        if d is None or d > today_d or d < cutoff:
            continue
        active.add(meta["pattern"])

    emphasis = {m for m, tier in (priority_tiers or {}).items()
                if tier == "emphasis"}
    emphasis_patterns = {
        meta["pattern"] for meta in catalog.values()
        if meta.get("primary") in emphasis
        and not meta.get("is_warmup") and not meta.get("is_cardio")}
    reachable = active | emphasis_patterns

    by_pattern: dict[str, list[dict]] = {}
    for key, meta in sorted(catalog.items()):
        if key in ever_logged or key in banned:
            continue
        if meta["pattern"] not in reachable:
            continue
        if meta.get("is_warmup") or meta.get("is_cardio"):
            continue
        derived = derived_starting_load(
            key, e1rm, catalog, db, ROTATION_CANDIDATE_TARGET_REPS)
        if derived is None:                      # off-catalog; unreachable here
            continue
        # target_reps is stated once in the block header.
        derived.pop("target_reps", None)
        if meta["pattern"] not in active:
            derived["pattern_untrained_days"] = window_days
        by_pattern.setdefault(meta["pattern"], []).append(derived)

    out: list[dict] = []
    for pattern in sorted(by_pattern):
        out.extend(_pick_per_pattern(by_pattern[pattern], per_pattern,
                                     logged_by_pattern, catalog))
    if not out:
        return {}
    return {
        "derivation": (
            "load_kg = ref_e1rm / (1 + target_reps/30) x transfer x "
            f"{NOVELTY_DISCOUNT}, rounded to the equipment's increment. "
            "ref is the same-pattern sibling with the most recent logged "
            "history. transfer folds the equipment-class coefficient, the "
            "single-limb share where the reference is two-limb, and the "
            f"{NOVEL_COMPOUND_CAP} first-exposure cap on compounds; "
            f"{NOVELTY_DISCOUNT} is the first-exposure discount (2-3 RIR on "
            "an unfamiliar movement). load_basis says what the number rests "
            "on: like_for_like (same equipment, same laterality) is the only "
            "one that assumed nothing. load_kg is null when there is nothing "
            "honest to derive from — bodyweight, no_reference (no sibling "
            "with history) or unknown_transfer (no coefficient for the "
            "equipment pair). Treat a null as a genuine first exposure: "
            "pick a load controllable for target_reps, say so in the cue, "
            "and let the next session's log take over. Every load here is a "
            "FIRST-SESSION ceiling, not a target."),
        "target_reps":       ROTATION_CANDIDATE_TARGET_REPS,
        "novelty_discount":  NOVELTY_DISCOUNT,
        "compound_cap":      NOVEL_COMPOUND_CAP,
        "patterns":          len(by_pattern),
        "candidates":        out,
    }


# ---------------------------------------------------------- the payload
# A slot is at risk when the last reconciled window says the user does
# not actually do it: half its prescribed sets or fewer, or a whole
# prescription skipped. Those are the slots the superset rule has to
# protect, and the only ones a pure diff function cannot identify on its
# own.
AT_RISK_COMPLETION = 0.5


def block_payload(person: str, rows: list[dict], db: dict, catalog: dict,
                  today_d: date, deloads: list[str] | None = None,
                  adherence: dict | None = None,
                  e1rm: dict | None = None) -> dict:
    """The ``block`` payload: current block, boundary state, what to rotate.

    When no artifact exists yet the block is bootstrapped from a plan and
    marked ``source: "derived_from_plan"`` — the coach then has a
    concrete previous state to differ from on its very first run under
    this system, instead of a free pass.

    WHICH PLAN. Not simply the newest. If the newest plan on disk is
    dated ``today_d`` then it IS this generation's own plan, already
    written, and bootstrapping from it makes the "previous" block a copy
    of the thing being validated. The render validator then sees
    ``prev.started == plan_date``, correctly refuses to diff a plan
    against itself, and passes. Measured: the same plan and the same
    logs gave 0 rotation errors once the plan file existed and 27 before
    it did — which is exactly the agent's recovery loop (write plan,
    render fails, re-run /coach, passes). Stepping back one generation
    makes both paths agree, and it also stops the six-week block clock
    resetting to zero every time a plan is written.

    ``pending_reconciliation`` is the gym-floor drift: slots whose
    prescribed movement was never logged while a same-pattern movement
    was. Emitted rather than applied, because rewriting a persisted
    artifact is a WRITE and this is the read path. The performed movement
    is ALSO stamped on the slot as ``performed_instead``, because the
    rotation rules have to know that the user already voted with their
    behaviour — refusing to prescribe ``Dumbbell Rear Delt Fly`` as "only
    an equipment swap" while this list reports that the user did exactly
    that swap is the system arguing with its own observations.

    ``e1rm`` is ``estimated_1rm``. It is here for one field:
    ``stalled_sessions``, which is what makes ``stall_3_sessions`` a
    reason the validator can DERIVE rather than a field only a
    hand-edited artifact could ever carry.
    """
    # Three newest plans: the newest two bootstrap a block (see WHICH
    # PLAN above), and the one before the newest is the PRIOR GENERATION
    # the deload cadence needs to tell a crossing from a standing debt.
    plans = load_plans(person, today_d, limit=3, db=db)
    stored = read_block(person)
    source = "artifact"
    undiffable_reason = None
    if stored is None and plans:
        todays_plan = _parse_iso_date(plans[-1]["plan_date"]) == today_d
        base = plans[-2] if (todays_plan and len(plans) > 1) else (
            None if todays_plan else plans[-1])
        if base is None:
            undiffable_reason = (
                f"the only plan on disk is today's ({plans[-1]['plan_date']}), "
                f"so there is no earlier generation to differ from")
        else:
            stored = block_from_plan(base, catalog)
            source = "derived_from_plan"

    # R-05, first half. A benched movement must never reach a slot the
    # coach is told to copy. Applied HERE, before every downstream read —
    # reconciliation, at-risk marking, both projections — so there is no
    # path on which a benched slot survives into the payload. The bench
    # list is `adherence.benched` only: `bench_blocked` movements were
    # deliberately NOT benched because they are the last route into a
    # muscle, and dropping those would strand the muscle.
    stored, benched_removed = strip_benched_slots(
        stored, (adherence or {}).get("benched"))

    status = block_status(stored, today_d, deloads)

    # If today's plan is already on disk, the generation before it is the
    # prior one; if it is not, this run IS the next generation and the
    # newest plan on disk is the prior one.
    dates = [_parse_iso_date(p["plan_date"]) for p in plans]
    dates = [d for d in dates if d is not None]
    prior_gen = None
    if dates:
        prior_gen = dates[-2] if (len(dates) > 1 and dates[-1] == today_d) \
            else (None if dates[-1] == today_d else dates[-1])
    cadence = deload_cadence(deloads, today_d, prior_gen)

    changes: list[dict] = []
    if stored:
        start = _parse_iso_date(stored.get("started"))
        if start is not None:
            _, changes = reconcile_block_with_logs(
                stored, rows, db, catalog, start, today_d + timedelta(days=1))

    # Which slots the user demonstrably does not do. This is the seam
    # ``rotation_diff_errors`` cannot reach on its own: it is a pure
    # function of two blocks and a catalog, and "does the user actually
    # do this" lives in the ledger.
    #
    # ``closed_completion_rate`` is used, not ``completion_rate``.
    # The newest window opens the day the plan is written, so on the
    # generation that writes it every completion rate is 0 and every slot
    # reads at risk — which made the finding count depend on whether the
    # plan file happened to be on disk yet (17 against 23 on the same
    # inputs). ``consecutive_unperformed`` is computed over closed
    # windows only and stands whatever the newest one is doing.
    at_risk: set[str] = set()
    for e in (adherence or {}).get("per_exercise") or []:
        rate = e.get("closed_completion_rate")
        if (e.get("consecutive_unperformed") or 0) >= 1 or (
                rate is not None and rate <= AT_RISK_COMPLETION):
            at_risk.add((e.get("name") or "").strip().lower())

    # Stall counts, so ``stall_3_sessions`` is a reason the diff can
    # derive. SKILL.md marks the stall response REQUIRED and the only
    # sanctioned responses are a variation swap, a rep-range shift or a
    # deload of that lift; the swap was unreachable because the field
    # naming it could not be set from anywhere in the pipeline.
    stalls = {(n or "").strip().lower(): (v or {}).get("stalled_sessions")
              for n, v in (e1rm or {}).items()}
    substituted = {(c.get("session_type"), (c.get("planned") or "").lower()):
                   c.get("performed") for c in changes}

    slots_out = []
    for stype, slots in sorted((stored or {}).get("sessions", {}).items()):
        for s in slots:
            key = (s.get("exercise") or "").strip().lower()
            if key in at_risk:
                s["at_risk"] = True
            if stalls.get(key):
                s["stalled_sessions"] = stalls[key]
            performed = substituted.get((stype, key))
            if performed:
                s["performed_instead"] = performed
            slots_out.append({
                "session_type": stype,
                "position":     s.get("position"),
                "exercise":     s.get("exercise"),
                "tag":          s.get("tag"),
                "pattern":      s.get("pattern") or pattern_group(
                    s.get("exercise"), catalog),
                "blocks_held":  s.get("blocks_held"),
                "history":      s.get("history") or None,
                "superset_with": s.get("superset_with"),
                # The prescription this slot carried, so the next
                # generation's validator can tell a progressed carry-over
                # from a re-copied one. See `block_from_plan`.
                "dose":         s.get("dose"),
                "at_risk":      s.get("at_risk") or None,
                "stalled_sessions": s.get("stalled_sessions"),
                "performed_instead": s.get("performed_instead"),
                "must_rotate":  (s.get("tag") == "rotating"
                                 and status.get("boundary_due", False)),
                "anchor_overdue": (s.get("tag") == "anchor"
                                   and int(s.get("blocks_held") or 0)
                                   >= ANCHOR_MAX_BLOCKS),
            })
    return {
        "source":                  source if stored else "none",
        # CAN this block be differed against, and against what. A derived
        # block rebuilt from the plan under validation is not a
        # comparison, and until this said so out loud the answer "no
        # rotation errors" was indistinguishable from "no rotation check
        # ran". ``diffable`` is False only when there is genuinely
        # nothing earlier on record.
        "diffable":                bool(stored) and undiffable_reason is None,
        "undiffable_reason":       undiffable_reason,
        "diff_basis": (None if not stored else
                       "persisted artifact" if source == "artifact" else
                       f"plan {stored.get('derived_from_plan')}"),
        # The canonical artifact projection of the same slots. ``slots``
        # below is the flat, session-tagged view the coach reads;
        # ``sessions`` is the shape ``rotation_diff_errors`` and the
        # on-disk artifact use. One source (``stored``), two projections
        # rendered here in one place — and the artifact shape is what
        # carries the per-slot provenance (``at_risk``,
        # ``stalled_sessions``, ``performed_instead``) that a rotation
        # check needs and a flattening drops.
        "sessions":                (stored or {}).get("sessions") or None,
        # R-05. Whether this block's core slots may be carried forward,
        # and if not, exactly which `core_week_spec` axes copying them
        # would violate. Computed from the catalog and the spec — neither
        # of them coach-written — so nothing the coach writes can turn it
        # off. See `core_spec_conflicts` for why the artifact is marked
        # rather than rewritten.
        "core_spec":               core_spec_conflicts(stored, catalog, db=db),
        # Slots the ledger had already withdrawn and this block was still
        # carrying. Reported, not silently dropped.
        "benched_slots_removed":   benched_removed or None,
        "block_id":                status.get("block_id"),
        "started":                 status.get("started"),
        "age_weeks":               status.get("age_weeks"),
        "boundary_due":            status.get("boundary_due"),
        "boundary_reason":         status.get("boundary_reason"),
        # Weeks, not a date. ``boundary_due_by`` is a real field on the
        # persisted artifact — a block document is forward-looking by
        # nature — but the PAYLOAD is an as-of snapshot, and a payload
        # anchored at 2026-06-01 that contains the string "2026-07-10"
        # trips the horizon rule and every backtest that checks it. The
        # information survives; the future-dated string does not.
        "weeks_to_boundary":       (
            None if status.get("age_weeks") is None
            else round(max(BLOCK_MAX_WEEKS - status["age_weeks"], 0.0), 1)),
        # "This week's plan is intended to be low volume." A DIFFERENT
        # question from `boundary_due`, which says "rotate the exercise
        # selection" — see `deload_cadence` for the four combinations and
        # why all of them occur. Validators demote volume floors to
        # advisory on this flag; diversity axes stay blocking, because a
        # deload is a reason to do less, not a reason to do one thing.
        # A REACTIVE deload is not covered here: that comes from the
        # recovery gate, and a caller wanting "deload week at all" ORs the
        # two.
        "deload_prescribed":       cadence["prescribed"],
        "deload_reason":           cadence["reason"],
        "deload_source":           "cadence" if cadence["prescribed"] else None,
        # Still owed, whether or not this generation is the crossing.
        # Nine weeks without a deload is worth saying out loud even when
        # it relaxes nothing.
        "deload_cadence_due":      cadence["cadence_due"],
        "weeks_since_deload":      cadence["weeks_since_deload"],
        "last_deload":             cadence["last_deload"],
        "deload_cadence_weeks":    DELOAD_CADENCE_WEEKS,
        "max_weeks":               BLOCK_MAX_WEEKS,
        "anchor_change_reasons":   list(ANCHOR_CHANGE_REASONS),
        "rotation_history_depth":  ROTATION_HISTORY_DEPTH,
        "session_types":           (stored or {}).get("session_types") or None,
        "slots":                   slots_out,
        "pending_reconciliation":  changes,
        "persist_with": (
            "python3 -m workout_coach.lib.blocks write --person <Name> "
            "--from-plan <YYYY-MM-DD>"),
    }


def _cli(argv: list[str] | None = None) -> int:
    """Persist a block artifact from a generated plan.

    The read path derives a block when none exists, but a derived block
    is not a record — it disappears the moment the plan series moves on.
    This is how the coach writes one down at a boundary. Same
    lib-with-a-CLI arrangement as ``shared/exercises_database.py``.
    """
    import argparse
    import sys
    from .extract import load_exercises_db
    from shared.exercises_database import DATABASE_PATH

    ap = argparse.ArgumentParser(description="Training-block artifact (W5).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_show = sub.add_parser("show", help="print the persisted block")
    p_show.add_argument("--person", required=True)
    p_write = sub.add_parser("write", help="persist a block derived from a plan")
    p_write.add_argument("--person", required=True)
    p_write.add_argument("--from-plan", dest="from_plan", required=True,
                         help="plan date (YYYY-MM-DD) to derive slots from")
    args = ap.parse_args(argv)

    if args.cmd == "show":
        json.dump(read_block(args.person) or {}, sys.stdout,
                  ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    today = date.today()
    plan_d = _parse_iso_date(args.from_plan)
    plans = [p for p in load_plans(args.person, max(today, plan_d or today))
             if p["plan_date"] == args.from_plan]
    if not plans:
        print(f"ERROR: no plan dated {args.from_plan} for that person",
              file=sys.stderr)
        return 1
    catalog = load_pattern_catalog(load_exercises_db(DATABASE_PATH))
    block = block_from_plan(plans[0], catalog, prev_block=read_block(args.person))
    path = write_block(args.person, block)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(_cli())
