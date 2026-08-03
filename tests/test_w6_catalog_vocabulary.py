"""W6a — catalog and logging vocabulary.

Covers the five W6a changes:

1. the ``## FULL BODY (Compound)`` heading regex and the heading-coverage
   assertion that stops the next unparsed heading from reporting clean,
2. the four new CORE entries, in both parsers,
3. the alias additions and the ``Hanging knee raise`` de-collapse,
4. the hip-thrust synergist reconciliation,
5. the hold / carry duration backfill in ``canonicalize_logs``.
"""
from __future__ import annotations

import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from shared import exercises_database as exdb
from shared.canonicalize_logs import (
    RENAMES,
    canonicalize_csv,
    extract_hold_duration,
    load_canonical_names,
)
from shared.monthly_csv import MONTHLY_HEADERS
from workout_coach.lib.extract import load_exercises_db

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DB_PATH = _REPO_ROOT / "shared" / "exercises-database.md"

# The four entries W6a adds, verbatim, and where they belong.
NEW_ENTRIES = [
    ("Suitcase Carry", "Anti-Lateral-Flexion",
     "- Suitcase Carry [DB] — +traps, +forearms"),
    ("Ab Wheel Rollout", "Anti-Extension", "- Ab Wheel Rollout [BW]"),
    ("Hanging Knee Raise", "Flexion", "- Hanging Knee Raise [BW]"),
    ("Plate Around the World", "Anti-Rotation",
     "- Plate Around the World [Plate]"),
]


# ══════════════════════════════════════════════ 1. heading regex + coverage
class HeadingParseTests(unittest.TestCase):
    def test_full_body_heading_is_its_own_muscle(self) -> None:
        """The parenthetical qualifier no longer defeats the regex.

        Before the fix the eight FULL BODY entries were appended to
        ``NECK``'s default section because the walk never switched
        ``current_muscle``.
        """
        db = exdb.parse_database()
        self.assertIn("FULL BODY (Compound)", db["muscles"])
        fb = db["muscles"]["FULL BODY (Compound)"]["sections"]["_default"]
        self.assertEqual(len(fb), 8, f"expected 8 FULL BODY entries, got {fb}")
        self.assertTrue(
            any(e.startswith("Dumbbell Farmer Walk") for e in fb),
            "Dumbbell Farmer Walk must live under FULL BODY, not NECK",
        )
        neck = db["muscles"]["NECK"]["sections"]["_default"]
        self.assertEqual(
            [exdb.entry_canonical_name(e) for e in neck],
            ["Neck Flexion Machine", "Neck Extension Machine", "Neck Bridge"],
        )

    def test_every_level_2_heading_in_the_real_catalog_parses(self) -> None:
        raw = _DB_PATH.read_text(encoding="utf-8").splitlines()
        unparsed = [
            line for line in (r.rstrip() for r in raw)
            if exdb._ANY_H2_RE.match(line)
            and not exdb._MUSCLE_HEADING_RE.match(line)
        ]
        self.assertEqual(unparsed, [])

    def test_validate_is_clean_on_the_real_catalog(self) -> None:
        self.assertEqual(exdb.validate_database(), [])

    def test_validate_reports_an_unparsed_heading(self) -> None:
        """The guard, proven to bite. A heading the regex cannot read is
        the one defect ``validate_database`` used to be blind to, because
        the entries below it still surface under the previous muscle."""
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / "exercises-database.md"
            broken.write_text(
                _DB_PATH.read_text(encoding="utf-8")
                .replace("## FULL BODY (Compound)", "## Full-Body Compound!"),
                encoding="utf-8",
            )
            with _patched_db(broken):
                issues = exdb.validate_database()
        self.assertTrue(
            any("unparsed muscle heading" in i for i in issues),
            f"expected an unparsed-heading issue, got {issues!r}",
        )

    def test_propose_exercise_resolves_the_base_muscle_name(self) -> None:
        """``propose_exercise(primary_muscle="FULL BODY")`` used to error:
        the caller knows a muscle, not a heading with a qualifier."""
        with tempfile.TemporaryDirectory() as tmp:
            db_copy = Path(tmp) / "exercises-database.md"
            shutil.copy(_DB_PATH, db_copy)
            with _patched_db(db_copy):
                result = exdb.propose_exercise(
                    name="Trap Bar Carry", primary_muscle="FULL BODY",
                    section="_default", tags=["[BB]", "+traps"],
                )
                self.assertEqual(result["action"], "added", result)
                self.assertEqual(result["details"]["muscle"],
                                 "FULL BODY (Compound)")
                self.assertEqual(exdb.lookup("trap bar carry"),
                                 "Trap Bar Carry")

    def test_propose_exercise_appends_to_a_named_section(self) -> None:
        """Regression on the rewritten insertion walk: the ordinary
        ``### Section`` path must still append after the section's LAST
        entry, not before the next heading and not into a sibling."""
        with tempfile.TemporaryDirectory() as tmp:
            db_copy = Path(tmp) / "exercises-database.md"
            shutil.copy(_DB_PATH, db_copy)
            with _patched_db(db_copy):
                result = exdb.propose_exercise(
                    name="Copenhagen Plank", primary_muscle="CORE",
                    section="Anti-Lateral-Flexion", tags=["[BW]"],
                )
                self.assertEqual(result["action"], "added", result)
                section = (exdb.parse_database()["muscles"]["CORE"]
                           ["sections"]["Anti-Lateral-Flexion"])
            self.assertEqual(
                [exdb.entry_canonical_name(e) for e in section],
                ["Side Plank", "Suitcase Carry", "Copenhagen Plank"],
            )

    def test_propose_exercise_appends_to_a_mid_file_default_section(self) -> None:
        """CARDIO's default section is followed by another muscle heading,
        which exercises the walked-off-the-end branch."""
        with tempfile.TemporaryDirectory() as tmp:
            db_copy = Path(tmp) / "exercises-database.md"
            shutil.copy(_DB_PATH, db_copy)
            with _patched_db(db_copy):
                result = exdb.propose_exercise(
                    name="Ski Erg", primary_muscle="CARDIO",
                    section="_default", tags=["[Ski Erg]"],
                )
                self.assertEqual(result["action"], "added", result)
                cardio = (exdb.parse_database()["muscles"]["CARDIO"]
                          ["sections"]["_default"])
                wellness = (exdb.parse_database()["muscles"]["WELLNESS"]
                            ["sections"]["_default"])
            self.assertEqual(exdb.entry_canonical_name(cardio[-1]), "Ski Erg")
            self.assertEqual(len(wellness), 2)

    def test_propose_exercise_still_rejects_an_unknown_muscle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_copy = Path(tmp) / "exercises-database.md"
            shutil.copy(_DB_PATH, db_copy)
            with _patched_db(db_copy):
                result = exdb.propose_exercise(
                    name="Nonsense Lift", primary_muscle="SPLEEN",
                    section="_default", tags=["[BB]"],
                )
        self.assertEqual(result["action"], "error")


class _patched_db:
    """Point the module's file globals at a scratch copy for one block."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    def __enter__(self):
        self._prior = exdb.DATABASE_PATH
        exdb.DATABASE_PATH = self._db_path
        return self

    def __exit__(self, *exc) -> None:
        exdb.DATABASE_PATH = self._prior


# ══════════════════════════════════════════════════════ 2. the four entries
class NewCatalogEntryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = _DB_PATH.read_text(encoding="utf-8")
        self.parsed = exdb.parse_database()
        self.coach_db = load_exercises_db(_DB_PATH)

    def test_entry_lines_are_verbatim(self) -> None:
        for _, _, line in NEW_ENTRIES:
            self.assertIn(f"\n{line}\n", self.text,
                          f"missing catalog line: {line!r}")

    def test_entries_land_in_the_right_core_subsection(self) -> None:
        core = self.parsed["muscles"]["CORE"]["sections"]
        for name, subsection, _ in NEW_ENTRIES:
            names = [exdb.entry_canonical_name(e) for e in core[subsection]]
            self.assertIn(name, names,
                          f"{name!r} not under CORE / {subsection}")

    def test_parser_a_resolves_each_new_name(self) -> None:
        for name, _, _ in NEW_ENTRIES:
            self.assertEqual(exdb.lookup(name), name)

    def test_parser_b_resolves_each_new_name_to_core(self) -> None:
        for name, _, _ in NEW_ENTRIES:
            entry = self.coach_db.get(name.lower())
            self.assertIsNotNone(entry, f"{name!r} missing from Parser B")
            self.assertEqual(entry["primary"], "core", name)
            self.assertFalse(entry["lengthened"],
                             "no CORE entry may carry ◆")

    def test_suitcase_carry_shape(self) -> None:
        entry = self.coach_db["suitcase carry"]
        self.assertEqual(entry["equipment"], "DB")
        self.assertEqual(sorted(entry["synergists"]), ["forearms", "traps"])

    def test_plate_tag_survives_both_parsers(self) -> None:
        self.assertEqual(
            self.coach_db["plate around the world"]["equipment"], "Plate")
        self.assertIn("`[Plate]`", self.text,
                      "the [Plate] tag must be documented in the legend")

    def test_hanging_knee_raise_sits_immediately_after_hanging_leg_raise(self) -> None:
        flexion = [exdb.entry_canonical_name(e) for e in
                   self.parsed["muscles"]["CORE"]["sections"]["Flexion"]]
        self.assertEqual(
            flexion[flexion.index("Hanging Leg Raise") + 1],
            "Hanging Knee Raise",
        )

    def test_plate_around_the_world_is_not_a_flexion_movement(self) -> None:
        """Spec §4.2: it must never satisfy the flexion requirement.
        ``render_validators`` reads flexion membership straight out of the
        CORE ``Flexion`` subsection, so subsection placement IS the rule."""
        flexion = [exdb.entry_canonical_name(e) for e in
                   self.parsed["muscles"]["CORE"]["sections"]["Flexion"]]
        self.assertNotIn("Plate Around the World", flexion)
        self.assertNotIn("Suitcase Carry", flexion)
        self.assertNotIn("Ab Wheel Rollout", flexion)

    # Catalog size, as an arithmetic statement rather than a magic number.
    # Spec §6 puts catalog growth out of scope beyond the four W6a entries,
    # so any change to this total is a scope question, not a test bug.
    CATALOG_BASELINE = 234          # commit 67b2d03, the spec baseline
    CATALOG_ADDED_HIP_THRUST = 1    # Dumbbell Hip Thrust (this branch)
    CATALOG_ADDED_W6A = len(NEW_ENTRIES)
    # Incline Y-Raise, added 2026-08-02 on an explicit user decision. This
    # is a scope exception to spec §6, taken deliberately: `### Traps` held
    # only Dumbbell Shrug and Cable Shrug — ONE movement pattern in two
    # equipment flavours — so a rotating traps slot could never legally
    # rotate, and traps is an emphasis muscle this block. That made the
    # catalog, not the code, the thing blocking stage two. The Y-raise is
    # scapular upward rotation (lower/mid traps), a genuinely different
    # pattern from shrug elevation, which is what the rotation rule
    # requires. Equipment flavour would not have been enough.
    CATALOG_ADDED_TRAPS_ROTATION = 1
    # Cable External Rotation, merged from review-fixes-2026-07-13 on
    # 2026-08-03. It is the catalog's first primary external-rotator entry
    # and closes the satisfiability gap constants.py documents for that
    # muscle: the restated MEV of 3 had no movement that could reach it.
    CATALOG_ADDED_EXTERNAL_ROTATION = 1

    def test_catalog_grew_by_exactly_four(self) -> None:
        expected = (self.CATALOG_BASELINE + self.CATALOG_ADDED_HIP_THRUST
                    + self.CATALOG_ADDED_W6A
                    + self.CATALOG_ADDED_TRAPS_ROTATION
                    + self.CATALOG_ADDED_EXTERNAL_ROTATION)
        actual = len(exdb._all_canonical_names())
        self.assertEqual(
            actual, expected,
            f"catalog holds {actual} canonical names; expected {expected} = "
            f"{self.CATALOG_BASELINE} at the spec baseline (67b2d03) "
            f"+ {self.CATALOG_ADDED_HIP_THRUST} (Dumbbell Hip Thrust) "
            f"+ {self.CATALOG_ADDED_W6A} (W6a). "
            f"A different number means an entry was added or removed outside "
            f"W6a's scope (spec §6 closes catalog growth) — or that Parser A "
            f"started counting something that is not an exercise. Decide "
            f"which, then move the constant deliberately.",
        )

    # ── the constraint the concurrent workstreams depend on ──────────────
    def test_two_handed_carry_stays_out_of_core(self) -> None:
        """Suitcase Carry is core; Dumbbell Farmer Walk is not. Adding the
        first must not have contaminated the second (test_catalog_integrity
        pins this too — duplicated here because the two entries are one
        edit apart and the failure mode is a copy-paste)."""
        farmer = self.coach_db["dumbbell farmer walk"]
        self.assertIsNone(farmer["primary"])
        self.assertNotIn("core", farmer["synergists"])
        self.assertEqual(self.coach_db["suitcase carry"]["primary"], "core")


# ══════════════════════════════════════════════════════════════ 3. aliases
class AliasTests(unittest.TestCase):
    def test_farmers_walk_forms_all_resolve(self) -> None:
        """The whole movement was un-loggable by any name a human types —
        only the exact canonical resolved."""
        for typed in ("farmers walk", "farmer walk", "farmer's walk",
                      "farmer’s walk", "Farmers Walks", "farmers carry",
                      "DB Farmer Walk"):
            self.assertEqual(exdb.lookup(typed), "Dumbbell Farmer Walk",
                             f"{typed!r} did not resolve")

    def test_hanging_knee_raise_is_no_longer_collapsed(self) -> None:
        self.assertEqual(exdb.lookup("hanging knee raise"),
                         "Hanging Knee Raise")
        self.assertEqual(exdb.lookup("Hanging knee raises"),
                         "Hanging Knee Raise")
        self.assertEqual(exdb.lookup("hanging leg raise"), "Hanging Leg Raise")
        for row in exdb.parse_aliases():
            if row["canonical"] == "Hanging Leg Raise":
                lowered = [i.lower() for i in row["inputs"]]
                self.assertNotIn("hanging knee raise", lowered)

    def test_aliases_for_the_other_new_entries(self) -> None:
        cases = {
            "ab wheel": "Ab Wheel Rollout",
            "ab roller": "Ab Wheel Rollout",
            "around the world": "Plate Around the World",
            "plate halo": "Plate Around the World",
            "single arm farmer walk": "Suitcase Carry",
            "suitcase walk": "Suitcase Carry",
        }
        for typed, canonical in cases.items():
            self.assertEqual(exdb.lookup(typed), canonical, typed)

    def test_band_pull_apart_must_not_resolve(self) -> None:
        """Commit ``ff13d82`` removed all four ``[Band]`` catalog entries for
        the stated reason "no band equipment available". ``known_name_set()``
        includes alias INPUT strings and ``validate_workout_md`` uses that set
        as a hard render gate, so an alias row is the only thing that can
        silently re-permit band prescriptions. It must stay off-catalog.

        Pointing it at ``Dumbbell Rear Delt Fly`` also converted warm-up prep
        into emphasis-muscle volume: the entry was ``## WARMUP / ### Upper
        Body`` (no primary, zero credit) and every prescription of it is a
        warm-up bullet, but ``weekly_volume_per_muscle`` credits on
        ``reps > 0`` with no kg gate, so each one would have become a full
        1.0 rear-delt hard set.
        """
        for typed in ("Band Pull-Apart", "band pull apart", "Band Pullapart",
                      "Bandpull Apart", "Resistance Band Pull-Apart"):
            self.assertIsNone(
                exdb.lookup(typed),
                f"{typed!r} resolved — see ff13d82, no band equipment",
            )
        self.assertFalse(exdb.is_known_name("Band Pull-Apart"))

    def test_the_render_gate_still_rejects_band_pull_apart(self) -> None:
        """The gate ff13d82 relied on, proven live. A plan bullet naming the
        movement must be a hard render error, not a warning."""
        from workout_coach.lib import render_validators as rv

        rv._workout_exercise_name_set.cache_clear()
        try:
            errors, _ = rv.validate_workout_md(
                "# Workout plan\n\n## Workout 1\n"
                "- Band Pull-Apart: 15 /// 15\n"
            )
        finally:
            rv._workout_exercise_name_set.cache_clear()
        self.assertTrue(
            any("Band Pull-Apart" in e and "not in the canonical" in e
                for e in errors),
            f"expected an off-catalog render error, got {errors!r}",
        )

    def test_rowing_resolves_to_the_erg_not_a_back_machine(self) -> None:
        self.assertEqual(exdb.lookup("Rowing"), "Rowing Machine")
        self.assertEqual(exdb.lookup("erg"), "Rowing Machine")
        self.assertEqual(exdb.lookup("row machine without chest support"),
                         "Seated Row Machine")

    def test_no_alias_points_nowhere(self) -> None:
        canonicals = {n.lower() for n in exdb._all_canonical_names()}
        for row in exdb.parse_aliases():
            self.assertIn(row["canonical"].lower(), canonicals,
                          f"{row['inputs']!r} → {row['canonical']!r}")


# ══════════════════════════════════════════════════════════ 4. hip thrusts
class HipThrustConsistencyTests(unittest.TestCase):
    def test_no_hip_thrust_variant_credits_hamstrings(self) -> None:
        """One of five variants carried ``+hamstrings``; every variant now
        agrees.

        Scale, measured 2026-08-02 over the trailing 28 days: 0.5 credited
        hamstring sets/wk for one person and 0.0 for the other. The whole
        corpus holds four Dumbbell Hip Thrust sets in one session, so 4 x 0.5
        = 2.0 credited sets, ever. (An earlier draft claimed ~4.5 sets/wk —
        unmeasured, and wrong by about 9x.) The removal is safe because
        hamstrings sit at 5.0 / 5.5 against MEV 4, not because the tag was
        expensive.
        """
        db = load_exercises_db(_DB_PATH)
        variants = [n for n in db if "hip thrust" in n]
        self.assertGreaterEqual(len(variants), 5, variants)
        for name in variants:
            self.assertEqual(
                db[name]["synergists"], [],
                f"{name!r} credits {db[name]['synergists']!r} — every hip "
                f"thrust variant must agree",
            )

    def test_reverse_hyperextension_keeps_hamstrings(self) -> None:
        """The contrast case: knee extended, hamstring works long."""
        db = load_exercises_db(_DB_PATH)
        self.assertIn("hamstrings",
                      db["reverse hyperextension machine"]["synergists"])


# ══════════════════════════════════════ 4b. what the catalog prose may claim
class CatalogProseAccuracyTests(unittest.TestCase):
    """Numbers and citations in the catalog are read by a human deciding
    whether to keep a tag. A wrong one is a wrong decision, so pin them."""

    def setUp(self) -> None:
        self.text = _DB_PATH.read_text(encoding="utf-8")
        self.note = _note_block(self.text, "No hip-thrust variant")
        self.wheel = _note_block(self.text, "Ab Wheel Rollout is the")

    # ── the corrected hamstring figure ───────────────────────────────────
    def test_the_45_sets_per_week_figure_is_gone(self) -> None:
        """Measured reality is 0.5 sets/wk and 0.0; ~4.5 was out by ~9x."""
        self.assertFalse(
            "4.5 phantom hamstring" in _flat(self.text),
            "the unmeasured '~4.5 phantom hamstring sets/wk' figure is still "
            "in exercises-database.md",
        )
        if "~4.5" in self.note:
            # Naming the withdrawn figure is fine; presenting it as current
            # is not. If it appears, the retraction has to appear with it.
            self.assertIn("never measured", self.note)

    def test_the_measured_hamstring_figure_is_stated(self) -> None:
        """Measured against the CSVs, not asserted: four sets total, one
        session, 4 x 0.5 = 2.0 credited hamstring sets ever."""
        for fragment in ("0.5 credited hamstring sets/wk",
                         "four Dumbbell Hip Thrust sets",
                         "2.0 credited hamstring sets, ever",
                         "wrong by about 9x"):
            self.assertIn(fragment, self.note,
                          f"{fragment!r} missing from the hip-thrust note")

    def test_the_note_does_not_claim_to_restore_a_previous_state(self) -> None:
        """HEAD has no ``Dumbbell Hip Thrust`` entry, so this workstream ADDS
        one. Calling that a restoration hides a real volume change."""
        self.assertIn("ADDS the entry", self.note)
        self.assertIn("does not restore a previous state", self.note)

    def test_contreras_is_quoted_with_its_actual_numbers(self) -> None:
        for fragment in ("40.8%", "69.5%", "86.8%", "14.9%"):
            self.assertIn(fragment, self.note, fragment)

    def test_the_hamstring_call_is_labelled_an_inference(self) -> None:
        """There is no published EMG → set-credit mapping, so the conclusion
        is a judgement call and has to say so. "Never leaves a short,
        low-tension position" overstated 40.8% MVIC and is gone."""
        self.assertIn("INFERENCE, NOT MEASUREMENT", self.note)
        self.assertNotIn("never leaves a short", self.note)

    # ── F3: the ab-wheel citation ────────────────────────────────────────
    def test_the_wheel_note_does_not_claim_low_lumbar_compression(self) -> None:
        """Escamilla 2006 reports low lumbar PARASPINAL EMG AMPLITUDE and did
        no spine-load modelling; "low lumbar compression" is not a finding of
        that paper. It may only appear as the claim being withdrawn."""
        self.assertNotIn("at low lumbar compression", self.wheel)
        self.assertIn('cannot support a claim of "low lumbar compression"',
                      self.wheel)
        self.assertIn("low lumbar paraspinal EMG amplitude", self.wheel)
        self.assertIn("no biomechanical modelling", self.wheel)

    def test_the_wheel_note_carries_the_studys_own_caution(self) -> None:
        self.assertIn("most effective in activating extraneous musculature",
                      self.wheel)

    def test_the_wheel_note_hedges_the_device(self) -> None:
        """The companion paper found the commercial Ab Roller no better than
        a crunch, so the top-tier result is Power-Wheel-specific."""
        self.assertIn("Power Wheel", self.wheel)
        self.assertIn("36(2):45-57", self.wheel)
        self.assertIn("Ab Roller no better than", self.wheel)


def _flat(text: str) -> str:
    """Collapse every whitespace run to one space.

    Prose assertions must survive a re-wrap: where the line breaks fall is a
    formatting decision, not the thing under test (F10).
    """
    return " ".join(text.split())


def _note_block(text: str, needle: str) -> str:
    """Return the whole parenthetical catalog note containing ``needle``.

    A note can span several paragraphs, so this runs from the line holding
    ``needle`` to the first line that closes with ``)``. Whitespace is
    normalized on the way out.
    """
    start = text.index(needle)
    end = text.index(")\n", start)
    return _flat(text[start:end + 1])


# ═══════════════════════════════════ 5. hold / carry duration backfill
class ExtractHoldDurationTests(unittest.TestCase):
    def test_parses_seconds_minutes_and_mmss(self) -> None:
        cases = {
            "30s hold": (0.5, ""),
            "45 sec": (0.75, ""),
            "90 seconds hold": (1.5, ""),
            "2min hold": (2.0, ""),
            "1:30": (1.5, ""),
            "40sec per side": (2.0 / 3.0, "per side"),
            "30s hold, felt easy": (0.5, "felt easy"),
        }
        for notes, (minutes, remaining) in cases.items():
            got_min, got_rest, reason = extract_hold_duration(notes)
            self.assertIsNone(reason, notes)
            self.assertAlmostEqual(got_min, minutes, places=6, msg=notes)
            self.assertEqual(got_rest, remaining, notes)

    def test_reports_rather_than_guesses(self) -> None:
        for notes in ("max hold", "2 holds", "hold to failure",
                      "hang as long as possible"):
            minutes, _, reason = extract_hold_duration(notes)
            self.assertIsNone(minutes, notes)
            self.assertIsNotNone(reason, notes)

    def test_conflicting_durations_are_ambiguous(self) -> None:
        minutes, _, reason = extract_hold_duration("30s then 45s")
        self.assertIsNone(minutes)
        self.assertIn("different durations", reason or "")

    def test_repeated_identical_durations_are_not_ambiguous(self) -> None:
        minutes, remaining, reason = extract_hold_duration("30s hold, 30s")
        self.assertIsNone(reason)
        self.assertAlmostEqual(minutes, 0.5)
        self.assertEqual(remaining, "")

    def test_metres_are_never_read_as_minutes(self) -> None:
        """A carry's ``30m`` is distance. Bare ``m`` is deliberately not a
        minutes unit; the row is reported instead of silently turned into
        a 30-minute hold."""
        minutes, _, reason = extract_hold_duration("30m carry per hand")
        self.assertIsNone(minutes)
        self.assertIsNotNone(reason)

    def test_a_plain_annotation_is_left_alone(self) -> None:
        for notes in ("felt heavy", "beltless", "8-10 reps", "per side"):
            minutes, remaining, reason = extract_hold_duration(notes)
            self.assertIsNone(minutes, notes)
            self.assertIsNone(reason, notes)
            self.assertEqual(remaining, notes)

    def test_implausible_durations_are_refused(self) -> None:
        minutes, _, reason = extract_hold_duration("hold 120 minutes")
        self.assertIsNone(minutes)
        self.assertIn("implausible", reason or "")


# ══════════════════════════ 5b. F4 — the notes the backfill used to mangle
class MangledHoldNoteTests(unittest.TestCase):
    """One test per reviewer-demonstrated failure.

    Every row below either wrote a wrong number into a typed column or
    disappeared without a line of output. The gate on the backfill is
    rep-less + manual + blank Duration; it had no exercise-kind or context
    gate at all, so a pace, a rest interval and a session length all looked
    like holds.
    """

    def test_h_mm_ss_is_not_read_as_m_ss(self) -> None:
        """``'1:00:00'`` matched the MM:SS branch on its leading ``1:00`` and
        wrote a ONE-MINUTE hold for a one-hour value — wrong by 60x — leaving
        ``'00'`` behind in Notes. It now parses as 60 min and is refused for
        being implausible as a single hold."""
        minutes, remaining, reason = extract_hold_duration("1:00:00")
        self.assertIsNone(minutes)
        self.assertIn("implausible", reason or "")
        self.assertIn("60.00", reason or "")
        self.assertEqual(remaining, "1:00:00")

    def test_h_mm_ss_inside_the_band_parses_to_the_full_value(self) -> None:
        """``parsing-rules.md`` promises H:MM:SS support; prove the branch
        computes hours rather than merely being rejected."""
        minutes, _, reason = extract_hold_duration("0:02:30 hold")
        self.assertIsNone(reason)
        self.assertAlmostEqual(minutes, 2.5)

    def test_a_pace_is_not_work_time(self) -> None:
        minutes, remaining, reason = extract_hold_duration("5:30 pace")
        self.assertIsNone(minutes)
        self.assertIn("pace", reason or "")
        self.assertEqual(remaining, "5:30 pace")

    def test_a_rest_interval_is_not_work_time(self) -> None:
        minutes, remaining, reason = extract_hold_duration(
            "rest 90s between sets")
        self.assertIsNone(minutes)
        self.assertIsNotNone(reason)
        self.assertEqual(remaining, "rest 90s between sets")

    def test_two_per_side_holds_are_not_collapsed(self) -> None:
        """Both sides are 30s, so the de-dupe path saw one value and wrote
        ``0:30`` — throwing away half the work."""
        minutes, _, reason = extract_hold_duration(
            "left side 30s right side 30s")
        self.assertIsNone(minutes)
        self.assertIn("per-side", reason or "")

    def test_a_set_count_prefix_is_reported_not_skipped(self) -> None:
        """``3x30s``: the lookbehind that protects against ``138.2`` also
        blinded the matcher to a digit-prefixed token, and no hold word meant
        no report either."""
        minutes, _, reason = extract_hold_duration("3x30s")
        self.assertIsNone(minutes)
        self.assertIsNotNone(reason, "3x30s vanished silently")
        self.assertIn("30s", reason or "")

    def test_bare_metres_without_a_hold_word_are_reported(self) -> None:
        """``30m carry`` was reported only because ``carry`` is a hold word.
        ``30m each hand`` has none, so it vanished."""
        minutes, _, reason = extract_hold_duration("30m each hand")
        self.assertIsNone(minutes)
        self.assertIsNotNone(reason, "30m each hand vanished silently")
        self.assertIn("30m", reason or "")

    def test_filler_stripping_leaves_meaningful_words(self) -> None:
        """``each`` was in the filler list, so ``'30s hold each side'`` was
        reduced to the bare word ``'side'``."""
        minutes, remaining, reason = extract_hold_duration(
            "30s hold each side")
        self.assertIsNone(reason)
        self.assertAlmostEqual(minutes, 0.5)
        self.assertEqual(remaining, "each side")

    def test_the_hold_ceiling_is_twenty_minutes(self) -> None:
        from shared.canonicalize_logs import MAX_HOLD_MIN

        self.assertEqual(MAX_HOLD_MIN, 20.0)
        self.assertIsNone(extract_hold_duration("hold 25 minutes")[0])
        self.assertAlmostEqual(extract_hold_duration("hold 15 minutes")[0],
                               15.0)


def _row(exercise: str, reps: str = "0", notes: str = "",
         duration: str = "", source: str = "manual",
         kg: str = "0") -> list[str]:
    row = [""] * len(MONTHLY_HEADERS)
    row[MONTHLY_HEADERS.index("SESSION")] = "1"
    row[MONTHLY_HEADERS.index("Date")] = "2026-03-17"
    row[MONTHLY_HEADERS.index("#")] = "1"
    row[MONTHLY_HEADERS.index("Exercise")] = exercise
    row[MONTHLY_HEADERS.index("Set")] = "1"
    row[MONTHLY_HEADERS.index("Reps")] = reps
    row[MONTHLY_HEADERS.index("kg")] = kg
    row[MONTHLY_HEADERS.index("Notes")] = notes
    row[MONTHLY_HEADERS.index("Duration (min)")] = duration
    row[MONTHLY_HEADERS.index("Source")] = source
    return row


class BackfillCsvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "2026.03.csv"
        self.canonical = load_canonical_names(_DB_PATH)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _write(self, rows: list[list[str]]) -> None:
        with self.path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(MONTHLY_HEADERS)
            w.writerows(rows)

    def _read(self) -> list[list[str]]:
        with self.path.open("r", encoding="utf-8", newline="") as f:
            return list(csv.reader(f))[1:]

    def test_moves_a_hold_time_and_blanks_the_note(self) -> None:
        self._write([_row("Dead Hang", notes="30s hold")])
        report = canonicalize_csv(self.path, self.canonical)
        self.assertEqual(report["durations"], 1)
        row = self._read()[0]
        self.assertEqual(row[MONTHLY_HEADERS.index("Duration (min)")], "0:30")
        self.assertEqual(row[MONTHLY_HEADERS.index("Notes")], "")

    def test_keeps_the_qualitative_remainder(self) -> None:
        self._write([_row("Side Plank", notes="40sec per side")])
        canonicalize_csv(self.path, self.canonical)
        row = self._read()[0]
        self.assertEqual(row[MONTHLY_HEADERS.index("Duration (min)")], "0:40")
        self.assertEqual(row[MONTHLY_HEADERS.index("Notes")], "per side")

    def test_dry_run_writes_nothing_but_reports_everything(self) -> None:
        self._write([_row("Dead Hang", notes="30s hold")])
        before = self.path.read_text(encoding="utf-8")
        report = canonicalize_csv(self.path, self.canonical, dry_run=True)
        self.assertEqual(report["durations"], 1)
        self.assertEqual(len(report["duration_moves"]), 1)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)

    def test_is_idempotent(self) -> None:
        self._write([_row("Dead Hang", notes="30s hold")])
        canonicalize_csv(self.path, self.canonical)
        after_first = self.path.read_text(encoding="utf-8")
        second = canonicalize_csv(self.path, self.canonical)
        self.assertEqual(second["durations"], 0)
        self.assertEqual(second["duration_ambiguous"], [])
        self.assertEqual(self.path.read_text(encoding="utf-8"), after_first)

    def test_unrecoverable_notes_are_reported_and_untouched(self) -> None:
        self._write([_row("Dead Hang", notes="max hold")])
        report = canonicalize_csv(self.path, self.canonical)
        self.assertEqual(report["durations"], 0)
        self.assertEqual(len(report["duration_ambiguous"]), 1)
        row = self._read()[0]
        self.assertEqual(row[MONTHLY_HEADERS.index("Notes")], "max hold")
        self.assertEqual(row[MONTHLY_HEADERS.index("Duration (min)")], "")

    def test_a_row_with_reps_is_never_touched(self) -> None:
        self._write([_row("Ab Crunch Machine", reps="10", kg="30",
                          notes="30s rest")])
        report = canonicalize_csv(self.path, self.canonical)
        self.assertEqual(report["durations"], 0)
        self.assertEqual(self._read()[0][MONTHLY_HEADERS.index("Notes")],
                         "30s rest")

    def test_an_imported_row_is_never_touched(self) -> None:
        self._write([_row("Treadmill Run", reps="", notes="45s pickup",
                          source="apple")])
        report = canonicalize_csv(self.path, self.canonical)
        self.assertEqual(report["durations"], 0)
        self.assertEqual(report["duration_ambiguous"], [])

    def test_a_populated_duration_is_never_overwritten(self) -> None:
        self._write([_row("Dead Hang", notes="30s hold", duration="0:45")])
        report = canonicalize_csv(self.path, self.canonical)
        self.assertEqual(report["durations"], 0)
        self.assertEqual(len(report["duration_ambiguous"]), 1)
        self.assertIn("Duration already",
                      report["duration_ambiguous"][0][3])
        self.assertEqual(
            self._read()[0][MONTHLY_HEADERS.index("Duration (min)")], "0:45")

    def test_rowing_orphan_is_renamed_to_the_erg(self) -> None:
        self.assertEqual(RENAMES["rowing"], "Rowing Machine")
        self._write([_row("Rowing", reps="", duration="5:24")])
        report = canonicalize_csv(self.path, self.canonical)
        self.assertEqual(report["renamed"], 1)
        self.assertEqual(self._read()[0][MONTHLY_HEADERS.index("Exercise")],
                         "Rowing Machine")

    # ── F5: RENAMES needs the same Source gate the backfill has ──────────
    def test_renames_never_touch_an_importer_owned_row(self) -> None:
        """The ``rowing`` rename shipped with a comment claiming no importer
        emits ``Rowing``. That holds for the auto-cardio path only:
        ``workout_sessions.csv`` carries four Apple ``Rowing`` sessions and an
        Apple-sourced ``Rowing`` row already sits in a monthly CSV. Rewriting
        it means fighting the importer on the next run; the honest outcome is
        that it surfaces in ``unknown_exercises``.
        """
        self._write([_row("Rowing", reps="", duration="5:24", source="apple")])
        report = canonicalize_csv(self.path, self.canonical)
        self.assertEqual(report["renamed"], 0)
        self.assertEqual(self._read()[0][MONTHLY_HEADERS.index("Exercise")],
                         "Rowing")

    def test_renames_still_apply_to_a_short_legacy_row(self) -> None:
        """17-column rows predate the ``Source`` column; the migration pads
        them to blank, i.e. user-owned. The gate must not freeze them out."""
        short = _row("Deadhang", reps="", notes="")[:-1]
        self._write([short])
        report = canonicalize_csv(self.path, self.canonical)
        self.assertEqual(report["renamed"], 1)
        self.assertEqual(self._read()[0][MONTHLY_HEADERS.index("Exercise")],
                         "Dead Hang")


class ParsingRulesDocTests(unittest.TestCase):
    """The rule `/log` violated is now stated as a rule, not a preference."""

    def setUp(self) -> None:
        raw = (_REPO_ROOT / "workout-logger" / "references"
               / "parsing-rules.md").read_text(encoding="utf-8")
        self.text = raw
        # Assert against a re-wrap-proof form: where the line breaks fall in
        # a prose file is a formatting decision, not the contract (F10). The
        # previous version pinned ``"MUST be written to\n`duration_min`"``
        # and would have failed on a one-word reflow.
        self.flat = _flat(raw)

    def test_holds_and_carries_section_exists_and_forbids_notes(self) -> None:
        self.assertIn("## Holds and carries", self.text)
        self.assertIn("MUST be written to `duration_min`", self.flat)
        self.assertIn("Never put a duration, a hold time, or a carry "
                      "distance in Notes", self.flat)

    def test_h_mm_ss_is_promised_by_the_doc_and_honoured_by_the_code(self) -> None:
        """The doc promised ``H:MM:SS``; the backfill read only ``MM:SS``."""
        self.assertIn("accepts `MM:SS`, `H:MM:SS`, or decimal minutes",
                      self.flat)
        self.assertAlmostEqual(extract_hold_duration("0:02:30")[0], 2.5)

    def test_the_assertions_are_decoupled_from_the_line_wrap(self) -> None:
        """F10, as a property rather than a promise. The superseded form
        pinned ``"MUST be written to\\n`duration_min`"`` — a literal line
        break inside a prose sentence. Re-flow the file and that assertion
        dies while the sentence it was testing is untouched; the flattened
        form survives, which is the whole point."""
        reflowed = _flat(self.text)
        self.assertNotIn("MUST be written to\n`duration_min`", reflowed,
                         "the old wrap-coupled assertion would still pass")
        self.assertIn("MUST be written to `duration_min`", reflowed)


class ValidateDatabaseCostTests(unittest.TestCase):
    """F8 — `Skills/CLAUDE.md` names reparsing static markdown inside one
    command as the first waste to remove."""

    def test_validate_reads_the_catalog_exactly_once(self) -> None:
        calls: list[int] = []
        real = exdb._read_database_text

        def counting() -> str:
            calls.append(1)
            return real()

        exdb._read_database_text = counting
        try:
            issues = exdb.validate_database()
        finally:
            exdb._read_database_text = real
        self.assertEqual(issues, [])
        self.assertEqual(
            len(calls), 1,
            f"validate_database read exercises-database.md {len(calls)}x; "
            f"one read, one parse",
        )


if __name__ == "__main__":
    unittest.main()
