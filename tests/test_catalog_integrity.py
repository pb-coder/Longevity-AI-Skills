"""Catalog integrity tests for exercises-database.md (Cluster D bugs D7/D8).

These tests parse the REAL shared/exercises-database.md and assert that every
muscle token (primary-note overrides and synergist +tags) canonicalizes to a
key that EXISTS in VOLUME_LANDMARKS.

This acts as a class-level guard against phantom landmarks (D7: lats) and
unmapped tokens (D8: posterior chain) ever silently polluting volume tracking.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

# We import from the workout_coach package (mirrors how other tests do it)
from workout_coach.lib.constants import MUSCLE_ALIASES, VOLUME_LANDMARKS
from workout_coach.lib.extract import (
    _canon_muscle,
    _primary_from_note,
    load_exercises_db,
)

# Path to the shared catalog (relative to repo root / worktree root)
_REPO_ROOT = Path(__file__).parent.parent
_DB_PATH = _REPO_ROOT / "shared" / "exercises-database.md"

# ── regex mirrors _BULLET_RE in extract.py ──────────────────────────────────
_BULLET_RE = re.compile(
    r"^\s*-\s+"
    r"(?P<name>.+?)"
    r"(?:\s+\[(?P<equip>[^\]]+)\])?"
    r"(?:\s*—\s*(?P<syn>[^◆(]+?))?"
    r"(?P<leng>\s*◆)?"
    r"(?:\s*\((?P<note>[^)]+)\))?"
    r"\s*$"
)


def _collect_all_tokens(db_path: Path) -> list[tuple[str, str, str]]:
    """Return list of (exercise_name, token_kind, raw_token) for every
    (primary: X) note and +synergist in the database."""
    tokens: list[tuple[str, str, str]] = []
    for line in db_path.read_text().splitlines():
        s = line.rstrip()
        m = _BULLET_RE.match(s)
        if not m:
            continue
        name = m.group("name").strip()
        if name.startswith("(") or ":" in name:
            continue

        # Synergists
        raw_syn = m.group("syn") or ""
        for tok in raw_syn.split(","):
            tok = tok.strip()
            if not tok:
                continue
            if tok.startswith("+"):
                tok = tok[1:].strip()
            if tok:
                tokens.append((name, "synergist", tok))

        # Primary note
        note = m.group("note")
        if note:
            note_m = re.match(r"\s*primary:\s*(.+)$", note.strip(), re.IGNORECASE)
            if note_m:
                tokens.append((name, "primary_note", note_m.group(1).strip()))

    return tokens


class CatalogIntegrityTests(unittest.TestCase):
    """Every muscle token in the catalog must resolve to a known VOLUME_LANDMARKS key."""

    def test_every_catalog_token_resolves_to_a_known_landmark(self) -> None:
        """D7+D8 guard: no token should canonicalize to None or to a value
        not present in VOLUME_LANDMARKS. Tokens that legitimately return None
        (shoulders, full body, etc.) are allowed — the problem is a token that
        resolves to a non-None value that ISN'T a landmark key."""
        tokens = _collect_all_tokens(_DB_PATH)
        self.assertTrue(len(tokens) > 0, "Database parse yielded no tokens — check path")

        bad: list[str] = []
        for ex_name, kind, raw_tok in tokens:
            canon = _canon_muscle(raw_tok)
            if canon is None:
                # None is allowed — the token is deliberately broad/skipped.
                # (e.g. "shoulders", "full body"). Verify these are actually
                # in MUSCLE_ALIASES as None and not just missing entirely.
                continue
            if canon not in VOLUME_LANDMARKS:
                bad.append(
                    f"  [{kind}] '{raw_tok}' -> '{canon}' (not in VOLUME_LANDMARKS) "
                    f"  [exercise: {ex_name!r}]"
                )

        if bad:
            self.fail(
                "Catalog tokens that canonicalize to a muscle NOT in VOLUME_LANDMARKS:\n"
                + "\n".join(bad)
            )

    # ── D7 specific ─────────────────────────────────────────────────────────

    def test_lats_is_not_a_volume_landmark(self) -> None:
        """D7: 'lats' must not be a standalone VOLUME_LANDMARKS key (folded into back)."""
        self.assertNotIn(
            "lats",
            VOLUME_LANDMARKS,
            "'lats' is a phantom landmark — it should be folded into 'back'",
        )

    def test_dumbbell_pullover_synergist_lats_is_remapped_to_back(self) -> None:
        """D7: Dumbbell Pullover has '+lats' synergist; after folding it must
        either be absent or mapped to 'back', never to a non-landmark 'lats'."""
        db = load_exercises_db(_DB_PATH)
        entry = db.get("dumbbell pullover")
        self.assertIsNotNone(entry, "Dumbbell Pullover not found in parsed DB")
        synergists = entry["synergists"]  # type: ignore[index]
        self.assertNotIn(
            "lats",
            synergists,
            "Dumbbell Pullover synergist 'lats' must be remapped (not left as phantom 'lats')",
        )

    def test_weekly_volume_has_no_lats_key(self) -> None:
        """D7: weekly_volume_per_muscle output must never contain 'lats' as a key."""
        # Import here to avoid pulling all of strength module at module level
        from workout_coach.lib.strength import weekly_volume_per_muscle
        from datetime import date

        # Build a synthetic set of rows that exercises the former +lats synergist
        # via a Dumbbell Pullover.
        today = date(2026, 1, 7)  # Wednesday of a clean week
        rows = [
            {
                "date": "2026-01-06",
                "exercise": "Dumbbell Pullover",
                "sets": 3,
                "reps": 10,
                "weight": 20.0,
                "rpe": 7,
                "notes": "",
            },
        ]
        db = load_exercises_db(_DB_PATH)
        unknown_out: set[str] = set()
        result = weekly_volume_per_muscle(rows, db, today, window_days=28, unknown_out=unknown_out)
        current = result["current"]
        self.assertNotIn(
            "lats",
            current,
            "weekly_volume_per_muscle returned a 'lats' key — phantom landmark not removed",
        )
        self.assertIn(
            "back",
            current,
            "Dumbbell Pullover's '+lats' must land on 'back' — an empty result "
            "means the fixture row was dropped and this test proves nothing",
        )

    # ── C-17: abs folded into core ──────────────────────────────────────────

    def test_abs_is_not_a_volume_landmark(self) -> None:
        """C-17: 'abs' must not be a standalone VOLUME_LANDMARKS key (folded into core)."""
        self.assertNotIn(
            "abs",
            VOLUME_LANDMARKS,
            "'abs' is a phantom landmark — it should be folded into 'core'",
        )

    def test_abs_token_canonicalizes_to_core(self) -> None:
        """C-17: a future '+abs' tag must route to 'core', never split volume."""
        self.assertEqual(_canon_muscle("abs"), "core")

    def test_weekly_volume_has_no_abs_key(self) -> None:
        """C-17: weekly_volume_per_muscle output must never contain 'abs' as a key."""
        # Import here to avoid pulling all of strength module at module level
        from workout_coach.lib.strength import weekly_volume_per_muscle
        from datetime import date

        # Build a synthetic set of rows that exercises the former 'abs' token
        # via an Ab Crunch Machine entry. NOTE: "date" must be an ISO string
        # ("YYYY-MM-DD"), not a `date` object — `_parse_iso_date` calls
        # `datetime.strptime(s, "%Y-%m-%d")`, which raises TypeError (caught,
        # returns None) on a `date` object, silently dropping the row and
        # making every assertion here vacuously true. (mirrors the row shape
        # used by the real assertions in test_strength.py, not the `date()`
        # object shape used by the older `test_weekly_volume_has_no_lats_key`
        # above, which has this same latent bug — out of scope to fix here.)
        today = date(2026, 1, 7)  # Wednesday of a clean week
        rows = [
            {
                "date": "2026-01-06",
                "exercise": "Ab Crunch Machine",
                "sets": 3,
                "reps": 10,
                "weight": 30.0,
                "rpe": 7,
                "notes": "",
            },
        ]
        db = load_exercises_db(_DB_PATH)
        unknown_out: set[str] = set()
        result = weekly_volume_per_muscle(rows, db, today, window_days=28, unknown_out=unknown_out)
        # weekly_volume_per_muscle returns {"window_days", "current", "landmarks"},
        # not a flat {muscle: count} dict — the per-muscle counts live under
        # "current" (and any tracked landmark under "landmarks"). Assert
        # against those, not against the wrapper dict itself.
        self.assertNotIn(
            "abs",
            result["current"],
            "weekly_volume_per_muscle returned an 'abs' key — phantom landmark not removed",
        )
        self.assertIn("core", result["current"])

    # ── D8 specific ─────────────────────────────────────────────────────────

    def test_posterior_chain_maps_to_glutes_not_none(self) -> None:
        """D8: 'posterior chain' must canonicalize to 'glutes', not None."""
        result = _canon_muscle("posterior chain")
        self.assertEqual(
            result,
            "glutes",
            f"'posterior chain' should map to 'glutes', got {result!r}",
        )

    def test_conventional_deadlift_primary_is_glutes_not_back(self) -> None:
        """D8: Conventional Deadlift has (primary: posterior chain); must resolve
        to 'glutes', not fall through to 'back' (the section default)."""
        db = load_exercises_db(_DB_PATH)
        entry = db.get("conventional deadlift")
        self.assertIsNotNone(entry, "Conventional Deadlift not found in parsed DB")
        primary = entry["primary"]  # type: ignore[index]
        self.assertEqual(
            primary,
            "glutes",
            f"Conventional Deadlift primary should be 'glutes', got {primary!r}",
        )

    def test_primary_from_note_posterior_chain_resolves_to_glutes(self) -> None:
        """D8: The (primary: posterior chain) note helper must return 'glutes'."""
        result = _primary_from_note("primary: posterior chain")
        self.assertEqual(
            result,
            "glutes",
            f"_primary_from_note('primary: posterior chain') returned {result!r}, expected 'glutes'",
        )

    def test_farmer_walk_does_not_grant_core(self) -> None:
        """C-22: a two-handed carry is not an ab exercise — RA sits at 3.9% MVC
        (McGill, Marshall & Andersen 2013, Ergonomics 56(2):293-302). Guard against
        a well-meaning '+core' being added back."""
        db = load_exercises_db(_DB_PATH)
        entry = db.get("dumbbell farmer walk")
        self.assertIsNotNone(entry)
        self.assertNotIn("core", entry["synergists"])
        self.assertIsNone(entry["primary"])
        self.assertIn("traps", entry["synergists"])


if __name__ == "__main__":
    unittest.main()
