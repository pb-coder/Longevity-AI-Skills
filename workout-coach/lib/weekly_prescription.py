"""Validated, immutable weekly prescriptions and their Markdown projection."""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import re
from datetime import date, timedelta
from pathlib import Path

from shared.exercises_database import DATABASE_PATH, _all_canonical_names
from shared.person_paths import weekly_plans_dir
from shared.workout_context import equipment_context
from tracker.atomic_io import write_text_atomic
from .extract import load_exercises_db
from .exercise_fit import excluded_for_session, validate_person


class PublishError(ValueError):
    """An actionable publication failure, with individual repair messages."""

    def __init__(self, issues: list[str], *, kind: str = "validation") -> None:
        super().__init__("; ".join(issues))
        self.issues = issues
        self.kind = kind


def _date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _dose(item):
    unit = next(k for k in ('reps', 'seconds', 'metres') if k in item)
    suffix = {'reps': '', 'seconds': 's', 'metres': 'm'}[unit]
    result = f"{item[unit]}{suffix}"
    if item.get('load_kg') is not None:
        result = (f"{item['load_kg']}kgx{result}" if unit != 'seconds'
                  else f"1 x {result} @ {item['load_kg']}kg")
    if item.get('assistance_kg') is not None:
        result += f" assisted {item['assistance_kg']}kg"
    if item.get('warmup'):
        result += ' (warmup)'
    return result


def render_week(doc):
    lines = [f"# Workout plan — {doc['week_start']} to {doc['week_end']}", '']
    for i, session in enumerate(doc['sessions'], 1):
        label = session['type'] + (f" · {session['date']}" if session.get('date') else '')
        if session.get('gym'):
            label += f" · {session['gym']}"
        lines += [f"## Workout {i}: {label}", '']
        for exercise in session['exercises']:
            setup = [exercise[key] for key in ('machine', 'variant') if exercise.get(key)]
            if exercise.get('load_basis') == 'plates_only':
                setup.append('plates only')
            label = exercise['name'] + (f" ({', '.join(setup)})" if setup else '')
            lines.append(f"- {label}: " + ' /// '.join(_dose(s) for s in exercise['sets']))
            if exercise.get('cue'):
                lines.append(f"  — {exercise['cue']}")
        lines.append('')
    return '\n'.join(lines)


_MARKDOWN_CONTROLS = re.compile(r"[\x00-\x1f\x7f`*_<>\[\]#]")
_FALLBACK_LANGUAGE = re.compile(
    r"\b(?:if|unless|otherwise|skip|shorten|postpone|alternative|instead|tired|fatigue"
    r"|walk|walking|sore|exhausted|easier|bad day)\b", re.IGNORECASE,
)


def _text(value, limit=160, *, cue=False):
    return (
        isinstance(value, str) and 0 < len(value.strip()) <= limit
        and not _MARKDOWN_CONTROLS.search(value)
        and (not cue or not _FALLBACK_LANGUAGE.search(value))
    )


def _number(value, *, zero=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (value >= 0 if zero else value > 0))


def _fields(obj, allowed, where, errors):
    extra = set(obj) - allowed
    if extra:
        errors.append(f"{where}: unknown fields {sorted(map(str, extra))}")


def validate_week(doc: dict, tracker: dict) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(doc, dict) or not isinstance(tracker, dict):
        return ['draft and tracker must be JSON objects'], warnings
    _fields(doc, {'week_start', 'week_end', 'as_of', 'sessions'}, 'draft', errors)
    snapshot = tracker.get('weekly_plan')
    if not isinstance(snapshot, dict):
        return errors + ['tracker must contain a weekly_plan snapshot'], warnings
    start, end, as_of = (_date(doc.get(k)) for k in ('week_start', 'week_end', 'as_of'))
    if not start or not end or not as_of or end != start + timedelta(days=6) or as_of > end:
        errors.append('week must cover seven dates and as_of must not follow its end')
    for k in ('week_start', 'week_end', 'as_of'):
        if doc.get(k) != snapshot.get(k):
            errors.append(f'{k} differs from tracker weekly_plan')
    sessions = doc.get('sessions')
    if not isinstance(sessions, list) or len(sessions) != snapshot.get('session_count'):
        return errors + ['session count differs from tracker weekly_plan'], warnings
    names = set(_all_canonical_names())
    catalog = load_exercises_db(DATABASE_PATH)
    fit = tracker.get('exercise_fit') or {}
    doses = {x.get('exercise'): x for x in (tracker.get('next_dose') or {}).get('exercises', []) if isinstance(x, dict)}
    ids, dates = set(), []
    days = snapshot.get('training_days') or []
    for i, session in enumerate(sessions):
        label = f"sessions[{i}]"
        if not isinstance(session, dict):
            errors.append(f'{label}: must be an object')
            continue
        _fields(session, {'id', 'date', 'type', 'duration_min', 'gym', 'goal', 'reason', 'exercises'}, label, errors)
        sid = session.get('id')
        if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', sid) or sid in ids:
            errors.append(f'{label}: stable unique id required')
        else:
            ids.add(sid)
        for key in ('type', 'goal', 'reason', 'gym'):
            limit = 80 if key in ('type', 'gym') else 300
            if (key == 'type' or key in session) and not _text(session.get(key), limit, cue=key == 'type'):
                errors.append(f'{label}: {key} must be plain single-line text')
        raw_date = session.get('date')
        sd = _date(raw_date) if raw_date is not None else None
        if raw_date is not None and (not sd or not start or not end or not start <= sd <= end or sd.isoformat() != raw_date):
            errors.append(f'{label}: date outside week or malformed')
        if sd:
            dates.append(sd)
        historical = bool(sd and as_of and sd < as_of)
        duration = session.get('duration_min')
        target = snapshot.get('session_target_min')
        if not _number(duration) or (not historical and _number(target) and duration > target):
            errors.append(f'{label}: positive finite duration within available time required')
        exercises = session.get('exercises')
        if not isinstance(exercises, list) or not exercises:
            errors.append(f'{label}: exercises required')
            continue
        gym = session.get('gym', fit.get('default_gym'))
        working = 0
        for j, ex in enumerate(exercises):
            exercise_label = f"{label}.exercises[{j}]"
            if not isinstance(ex, dict):
                errors.append(f'{exercise_label}: invalid exercise')
                continue
            _fields(ex, {'name', 'sets', 'cue', 'machine', 'load_basis', 'variant'}, exercise_label, errors)
            name = ex.get('name')
            if not isinstance(name, str) or name not in names:
                errors.append(f'{exercise_label}.name: unknown or noncanonical exercise {name!r}')
                continue
            meta = catalog.get(name.lower(), {})
            if meta.get('is_cardio'):
                errors.append(f'{exercise_label}.name: cardio exercise is not a strength prescription')
            variant = ex.get('variant')
            for key in ('cue', 'machine', 'variant'):
                if key in ex and not _text(ex[key], cue=key == 'cue'):
                    errors.append(f'{exercise_label}.{key}: must be plain single-line text')
            if ex.get('load_basis') not in (None, 'total', 'plates_only'):
                errors.append(f'{exercise_label}.load_basis: invalid load_basis')
            if not historical and start and end and as_of:
                day = sd or None
                excluded = excluded_for_session(fit, day, gym, variant=variant)
                if not fit.get('restrictions') and gym == fit.get('default_gym'):
                    excluded = fit.get('excluded') or []
                possible = excluded_for_session(
                    fit, day, gym, variant=variant, possible_between=(max(as_of, start), end),
                )
                if name in excluded:
                    errors.append(f'{exercise_label}.name: excluded exercise {name!r}')
                elif name in possible:
                    errors.append(f'{exercise_label}: {name} eligibility needs date, gym or variant confirmation')
            sets = ex.get('sets')
            if not isinstance(sets, list) or not sets:
                errors.append(f'{exercise_label}.sets: sets required')
                continue
            for k, item in enumerate(sets):
                set_label = f"{exercise_label}.sets[{k}]"
                if not isinstance(item, dict):
                    errors.append(f'{set_label}: each set must be an object')
                    continue
                _fields(item, {'reps', 'seconds', 'metres', 'load_kg', 'assistance_kg', 'warmup'}, set_label, errors)
                units = [k for k in ('reps', 'seconds', 'metres') if k in item]
                if len(units) != 1:
                    errors.append(f'{set_label}: each set needs exactly one dose')
                    continue
                unit = units[0]
                value = item[unit]
                valid = (isinstance(value, (str, int)) and not isinstance(value, bool)
                         and bool(re.fullmatch(r'[1-9]\d*(?:-[1-9]\d*)?', str(value)))) if unit == 'reps' else _number(value)
                if unit == 'reps' and valid and '-' in str(value):
                    lo, hi = map(int, str(value).split('-'))
                    valid = lo <= hi
                if (not valid or any(not _number(item[k], zero=True) for k in ('load_kg', 'assistance_kg') if k in item)
                        or ('load_kg' in item and 'assistance_kg' in item)
                        or ('warmup' in item and not isinstance(item['warmup'], bool))):
                    errors.append(f'{set_label}: invalid set dose')
                if not item.get('warmup') and not meta.get('is_warmup'):
                    working += 1
            reference = doses.get(name)
            if not historical and reference and reference.get('load_kg') is not None:
                loads = [x.get('load_kg') for x in sets if isinstance(x, dict) and not x.get('warmup') and x.get('load_kg') is not None]
                context = reference.get('equipment_context')
                chosen_context = equipment_context({'gym': gym, 'machine': ex.get('machine')})
                if loads and context and chosen_context != equipment_context(context):
                    warnings.append(f'session {i + 1}: {name} has no comparable reference for this setup')
                elif loads and reference['load_kg'] not in loads and reference.get('other_gym_load_kg') not in loads:
                    warnings.append(f'session {i + 1}: {name} dose differs from reference; review equipment context')
        if not working:
            errors.append(f'{label}: at least one strength working set required')
        budget = tracker.get('target_working_sets')
        if not historical and isinstance(budget, int) and working > budget + 2:
            warnings.append(f'session {i + 1}: {working} working sets exceed the estimated time budget of {budget}')
    if dates != sorted(dates) or len(dates) != len(set(dates)):
        errors.append('scheduled session dates must be unique and ordered')
    if days:
        planned_days = sorted(d.isoformat() for d in dates if not as_of or d >= as_of)
        available_days = sorted(d for d in days if not as_of or (_date(d) and _date(d) >= as_of))
        upcoming_count = sum(not s.get('date') or not as_of or (_date(s.get('date')) and _date(s.get('date')) >= as_of) for s in sessions if isinstance(s, dict))
        if len(available_days) != upcoming_count or planned_days != available_days:
            errors.append('session dates must match all supplied training days')
    return errors, warnings


def read_week_revisions(person: str) -> list[tuple[Path, dict | None]]:
    """Read authoritative envelopes once. A null record marks invalid history."""
    revisions = []
    for path in sorted(weekly_plans_dir(person).glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            doc = record["prescription"]
            if (record["schema_version"] != 1 or type(record["revision"]) is not int
                    or not all(_date(doc[k]) for k in ("as_of", "week_start", "week_end"))
                    or not isinstance(doc["sessions"], list)):
                record = None
        except (OSError, ValueError, KeyError, TypeError):
            record = None
        revisions.append((path, record))
    return revisions


def latest_published_weeks(person: str, as_of: date, *,
                           revisions: list[tuple[Path, dict | None]] | None = None) -> list[dict]:
    """Latest revision per week known on as_of, including future weeks."""
    selected: dict[str, dict] = {}
    as_of_s = as_of.isoformat()
    for _, record in read_week_revisions(person) if revisions is None else revisions:
        if record is None or record["prescription"]["as_of"] > as_of_s:
            continue
        doc = record["prescription"]
        week = doc["week_start"]
        prior = selected.get(week)
        if prior is None or (doc["as_of"], record["revision"]) > (prior["prescription"]["as_of"], prior["revision"]):
            selected[week] = record
    return [selected[k] for k in sorted(selected)]


def _apply_amendment(base: dict, changes: dict, as_of: str) -> dict:
    """Replace existing slots by ID, preserving all untouched sessions."""
    replacements = changes.get("replacements") if isinstance(changes, dict) else None
    if not isinstance(replacements, list) or not replacements or set(changes) != {"replacements"}:
        raise PublishError(["amendment must contain a nonempty replacements list"])

    by_id = {}
    known = {session["id"] for session in base["sessions"]}
    for i, replacement in enumerate(replacements):
        session_id = replacement.get("id") if isinstance(replacement, dict) else None
        if not isinstance(session_id, str) or session_id not in known or session_id in by_id:
            raise PublishError([f"replacements[{i}].id: expected a unique existing session ID"])
        by_id[session_id] = replacement
    return {
        **base,
        "as_of": as_of,
        "sessions": [by_id.get(session["id"], session) for session in base["sessions"]],
    }


def publish_week(person: str, doc: dict, tracker: dict, *, amend: bool = False) -> dict:
    validate_person(person)
    snapshot = tracker.get("weekly_plan") if isinstance(tracker, dict) else None
    if not isinstance(snapshot, dict):
        raise PublishError(["tracker must contain a weekly_plan snapshot"])
    owner = snapshot.get("person")
    if owner is not None and owner != person:
        raise PublishError(["person differs from tracker weekly_plan"])
    expected = snapshot.get("observed_revision")
    if amend:
        if not all(_date(snapshot.get(key)) for key in ("week_start", "week_end", "as_of")):
            raise PublishError(["amendment requires a valid weekly_plan period and as_of"])
        existing = tracker.get("existing_week")
        if not isinstance(existing, dict):
            raise PublishError(["amendment requires an observed published week"], kind="history_conflict")
        if expected is None:
            expected = existing.get("revision")
        if type(expected) is not int or expected < 1:
            raise PublishError(["amendment requires a valid observed revision"])
        window, warnings = snapshot, []
    else:
        errors, warnings = validate_week(doc, tracker)
        if errors:
            raise PublishError(errors)
        window = doc
    if expected is not None and (type(expected) is not int or expected < 0):
        raise PublishError(["weekly_plan.observed_revision must be a nonnegative integer"])

    folder = weekly_plans_dir(person)
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.publish.lockfile').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        same_week = []
        for path, record in read_week_revisions(person):
            if record is None:
                if path.name.startswith(window['week_start'] + '-r'):
                    raise PublishError([f'corrupt weekly history: {path.name}'], kind="history_conflict")
                warnings.append(f'ignored corrupt unrelated weekly history: {path.name}')
                continue
            old = record['prescription']
            if old['week_start'] == window['week_start']:
                same_week.append((path, record))
            elif old['week_start'] <= window['week_end'] and window['week_start'] <= old['week_end']:
                raise PublishError(["weekly prescription overlaps another published week"], kind="history_conflict")

        same_week.sort(key=lambda item: item[1]["revision"])
        latest = same_week[-1][1] if same_week else None
        current_revision = latest["revision"] if latest else 0
        if amend:
            if latest is None:
                raise PublishError(["no published week to amend"], kind="history_conflict")
            doc = _apply_amendment(latest["prescription"], doc, snapshot["as_of"])
        already_current = latest is not None and latest["prescription"] == doc
        if expected is not None and expected != current_revision and not already_current:
            raise PublishError(
                [f"week changed from revision {expected} to {current_revision}. Refresh the tracker snapshot."],
                kind="stale_snapshot",
            )
        if amend:
            errors, draft_warnings = validate_week(doc, tracker)
            if errors:
                raise PublishError(errors)
            warnings.extend(draft_warnings)

        content = json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(content.encode()).hexdigest()[:16]
        rendered = render_week(doc)
        # An intentional reversion is a new revision. For guarded writes,
        # only the current revision can be an idempotent replay.
        replay_candidates = same_week[-1:] if expected is not None else same_week
        for path, record in replay_candidates:
            if record['digest'] == digest and record['prescription'] == doc:
                md = path.with_suffix('.md')
                if not md.exists() or md.read_text(encoding='utf-8') != rendered:
                    write_text_atomic(md, rendered)
                return {'prescription_path': str(path), 'workout_md_path': str(md), 'revision': record['revision'], 'warnings': warnings}
        old_done = {}
        if latest is not None:
            previous = latest['prescription']
            if doc['as_of'] < previous['as_of']:
                raise PublishError(["revision as_of cannot precede the preceding revision"], kind="history_conflict")
            old_done = {s['id']: s for s in previous['sessions'] if s.get('date') and s['date'] < doc['as_of']}
            new = {s['id']: s for s in doc['sessions']}
            if any(new.get(k) != v for k, v in old_done.items()):
                raise PublishError(["past dated sessions must remain unchanged in revisions"], kind="history_conflict")
        if any(s.get('date') and s['date'] < doc['as_of'] and old_done.get(s['id']) != s for s in doc['sessions']):
            raise PublishError(["new sessions cannot be dated before as_of"], kind="history_conflict")
        revision = current_revision + 1
        stem = f"{doc['week_start']}-r{revision:04d}-{digest}"
        md, path = folder / f'{stem}.md', folder / f'{stem}.json'
        record = {'schema_version': 1, 'revision': revision, 'digest': digest, 'prescription': doc}
        write_text_atomic(md, rendered)
        write_text_atomic(path, json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        return {'prescription_path': str(path), 'workout_md_path': str(md), 'revision': revision, 'warnings': warnings}
