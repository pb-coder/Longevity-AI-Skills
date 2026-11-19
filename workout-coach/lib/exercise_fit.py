"""Optional private coach profile and explicitly scoped exercise fit.

No observation of completion or omission establishes comfort or exclusion.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path

from shared.data_git import commit_data
from shared.exercises_database import lookup
from shared.person_paths import data_dir
from .adherence import read_bench_log


def validate_person(person: str) -> str:
    """Require a single nonempty person directory name."""
    if (not isinstance(person, str) or not person.strip() or person in {".", ".."}
            or "/" in person or "\\" in person or "\x00" in person):
        raise ValueError("person must be a single nonempty directory name")
    return person


def profile_path(person: str) -> Path:
    validate_person(person)
    return data_dir(person) / "coach_profile.json"


def _date(value):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(value) if value else None
    except (TypeError, ValueError):
        raise ValueError(f"Invalid profile date: {value!r}")


def _canonical(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Exercise must be a nonempty canonical name")
    result = lookup(name.strip())
    if result is None:
        raise ValueError(f"Unknown exercise: {name!r}")
    return result


def validate_profile(profile: dict) -> dict:
    """Validate and canonicalize a user-authored private profile."""
    if not isinstance(profile, dict):
        raise ValueError("Coach profile must be a JSON object")
    out = dict(profile)
    if out.get("default_gym") is not None and not isinstance(out["default_gym"], str):
        raise ValueError("default_gym must be a string")
    goals = out.get("goals", [])
    if not isinstance(goals, list):
        raise ValueError("goals must be an ordered list")
    cleaned_goals = []
    for goal in goals:
        if not isinstance(goal, dict) or goal.get("type") not in {"strength", "muscle_growth", "cardio", "swim", "general"}:
            raise ValueError("Each goal needs a supported type")
        item = dict(goal)
        if item.get("exercise"):
            item["exercise"] = _canonical(item["exercise"])
        if item["type"] == "strength" and not item.get("exercise"):
            raise ValueError("A strength goal needs a specific exercise")
        cleaned_goals.append(item)
    out["goals"] = cleaned_goals
    for field in ("preferences", "restrictions", "observations"):
        entries = out.get(field, [])
        if not isinstance(entries, list):
            raise ValueError(f"{field} must be a list")
        clean = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(f"{field} entries must be objects")
            item = dict(entry)
            item["exercise"] = _canonical(item.get("exercise"))
            for scope in ("location", "variant"):
                if item.get(scope) is not None and not isinstance(item[scope], str):
                    raise ValueError(f"{scope} must be a string")
            if field == "restrictions" and item.get("type") not in {"avoid", "limitation", "unavailable"}:
                raise ValueError("Restriction type must be avoid, limitation, or unavailable")
            if field == "observations" and item.get("type") not in {"effort", "discomfort", "preference"}:
                raise ValueError("Observation type must be effort, discomfort, or preference")
            start, end = _date(item.get("start_date")), _date(item.get("end_date"))
            _date(item.get("date"))
            if start and end and end < start:
                raise ValueError("Restriction end precedes start")
            clean.append(item)
        out[field] = clean
    inventory = out.get("equipment", {})
    if (not isinstance(inventory, dict) or
        any(not isinstance(k, str) or not isinstance(v, list) or
            any(not isinstance(item, str) for item in v) for k, v in inventory.items())):
        raise ValueError("equipment must map locations to lists of known equipment")
    out["equipment"] = inventory
    return out


def load_profile(person: str) -> dict:
    path = profile_path(person)
    if not path.exists():
        return validate_profile({})
    try:
        return validate_profile(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read coach profile: {exc}") from exc


def save_profile(person: str, profile: dict) -> Path:
    """Atomically save an explicit profile and record one data history entry."""
    profile = validate_profile(profile)
    path = profile_path(person)
    if path.exists():
        try:
            if load_profile(person) == profile:
                return path
        except ValueError:
            pass  # An explicit replacement can repair malformed JSON.
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(profile, indent=2, ensure_ascii=False) + "\n"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".coach-profile-", delete=False) as file:
            temporary = file.name
            file.write(content)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            os.unlink(temporary)
    commit_data(person, "coach: update profile")
    return path


def _same_location(a, b):
    return (a or "").strip().casefold() == (b or "").strip().casefold()


def _applies(rule, day, gym, variant=None, *, possible_between=None):
    possible = possible_between is not None
    if rule.get("variant") and not (possible and variant is None) and (
        variant is None or rule["variant"].casefold() != variant.casefold()
    ):
        return False
    scoped_location = rule.get("location_scoped") or rule.get("location") is not None
    if scoped_location and not (possible and gym is None) and (
        gym is None or not _same_location(rule.get("location"), gym)
    ):
        return False
    start, end = _date(rule.get("start_date")), _date(rule.get("end_date"))
    if day is None and possible:
        earliest, latest = possible_between
        return (not start or start <= latest) and (not end or end >= earliest)
    if day is None and (start or end):
        return False
    return (not start or day >= start) and (not end or day <= end)


def excluded_for_session(summary: dict, session_date: date | str | None, gym: str | None, *,
                         variant: str | None = None,
                         possible_between: tuple[date, date] | None = None) -> list[str]:
    """Return exclusions established for this date and location.

    None means unknown gym; pass an empty string for the legacy unnamed gym.
    A missing date cannot establish that a time-scoped rule applies. The
    With ``possible_between``, include unresolved rules that could apply in
    that period given the known date, gym and variant.
    """
    day = _date(session_date)
    rules = summary.get("restrictions") if isinstance(summary, dict) else []
    if not isinstance(rules, list):
        return []
    valid = []
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("exercise"), str):
            continue
        try:
            if _applies(rule, day, gym, variant, possible_between=possible_between):
                valid.append(rule["exercise"])
        except (TypeError, ValueError, AttributeError):
            continue
    return sorted(set(valid), key=str.casefold)


def exercise_fit_summary(person: str, week_start: date, week_end: date, *, history=None, as_of=None) -> dict:
    """Resolve explicit fit evidence and legacy decisions for a week.

    Optional history records contain exercise, date, outcome (completed,
    omitted, swapped), and optional gym/variant. Counts describe records,
    not comparative progression or movement tolerance.
    """
    start, end = _date(week_start), _date(week_end)
    if not start or not end or end < start:
        raise ValueError("A valid week start and end are required")
    anchor = _date(as_of) if as_of is not None else start
    profile = load_profile(person)
    legacy = read_bench_log(person)
    default_gym = (profile["default_gym"] if "default_gym" in profile
                   else legacy.get("current_gym") or "")
    restrictions = [dict(rule, source="profile") for rule in profile["restrictions"]]
    for entry in legacy.get("entries", []):
        if not isinstance(entry, dict) or not isinstance(entry.get("exercise"), str) or not entry["exercise"].strip():
            continue
        disposition = entry.get("disposition")
        if disposition not in {"retired", "unavailable"}:
            continue
        # Historical names should remain binding even if a catalog changes.
        exercise = lookup(entry["exercise"]) or entry["exercise"].strip()
        base = {"exercise": exercise, "type": disposition, "source": "legacy"}
        if disposition == "retired":
            restrictions.append(base)
        else:
            gyms = entry.get("unavailable_gyms")
            if not isinstance(gyms, list):
                gyms = [entry.get("gym")]
            for gym in gyms:
                if gym is None or isinstance(gym, str):
                    restrictions.append(dict(base, location=gym, location_scoped=True))
    summary = {"goals": profile["goals"], "default_gym": default_gym,
               "preferences": profile["preferences"], "equipment": profile["equipment"],
               "observations": [o for o in profile["observations"]
                                if not o.get("date") or _date(o["date"]) <= anchor],
               "restrictions": restrictions,
               "history": [], "excluded": []}
    summary["excluded"] = sorted({r["exercise"] for r in restrictions
        if _applies(r, start, default_gym) and _applies(r, end, default_gym)}, key=str.casefold)
    counts = {}
    seen = set()
    for row in history or []:
        if not isinstance(row, dict) or not isinstance(row.get("exercise"), str) or not row["exercise"].strip():
            continue
        try:
            day = _date(row.get("date"))
        except ValueError:
            continue
        if any(row.get(k) is not None and not isinstance(row[k], str) for k in ("gym", "variant")):
            continue
        if day is None or day > anchor:
            continue
        outcome = row.get("outcome", "completed")
        if outcome not in {"completed", "omitted", "swapped"}:
            continue
        name = lookup(row["exercise"]) or row["exercise"].strip()
        key = (name, row.get("gym"), row.get("variant"))
        observation_key = (key, day, outcome)
        if observation_key in seen:
            continue
        seen.add(observation_key)
        record = counts.setdefault(key, {"exercise": name, "gym": key[1], "variant": key[2],
                                         "completed": 0, "omitted": 0, "swapped": 0})
        record[outcome] += 1
    for record in counts.values():
        record["fit"] = "uncertain" if record["omitted"] + record["swapped"] >= 2 else "unknown"
        summary["history"].append(record)
    return summary
