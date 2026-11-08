"""Preflight and run explicitly paired workout and health imports.

Repeat --entry PERSON EXPORT WORKOUT_JSON for each person. Use '-' for an
omitted export or workout payload. Export ownership is supplied by the
caller and cannot be inferred from Health Export Kit content. Preview all
entries by default; pass --apply to write. A failure during application
stops subsequent entries but does not roll back earlier completed writes.
"""
from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

SKILLS_ROOT = Path(__file__).resolve().parents[1]
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from shared.import_health_export_kit import EmptyImportError, import_export  # noqa: E402
from shared.person_paths import person_dir  # noqa: E402

LOGGER = SKILLS_ROOT / 'workout-logger' / 'scripts' / 'append_workout.py'
IMPORTER = SKILLS_ROOT / 'shared' / 'import_health_export_kit.py'


def _load_logger():
    spec = importlib.util.spec_from_file_location('training_append_workout', LOGGER)
    if spec is None or spec.loader is None:
        raise RuntimeError('Could not load workout logger')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preflight(entries: list[list[str]]) -> list[tuple[str, Path | None, Path | None]]:
    """Check every entry before any writing; do not infer file ownership."""
    logger = _load_logger()
    people, exports, workouts = set(), set(), set()
    prepared = []
    for person, export, workout in entries:
        if not person or person in ('.', '..') or Path(person).name != person or '\\' in person:
            raise ValueError(f'Invalid person name: {person!r}')
        if person.casefold() in people:
            raise ValueError(f'Person listed more than once: {person}')
        people.add(person.casefold())
        if not (person_dir(person) / 'data').is_dir():
            raise ValueError(f'Tracker does not exist for {person}')
        export_path = None if export == '-' else Path(export).resolve(strict=True)
        workout_path = None if workout == '-' else Path(workout).resolve(strict=True)
        if not export_path and not workout_path:
            raise ValueError(f'No input supplied for {person}')
        if export_path:
            if not export_path.is_file() or export_path in exports:
                raise ValueError(f'Export is not a unique file: {export_path}')
            exports.add(export_path)
            preview = import_export(person, export_path, None, None, dry_run=True)
            print(f'{person} | export: {export_path}')
            for line in preview:
                print(f'  {line}')
        if workout_path:
            if not workout_path.is_file() or workout_path in workouts:
                raise ValueError(f'Workout payload is not a unique file: {workout_path}')
            workouts.add(workout_path)
            rows, bodyweight, css, sleep, nutrition = logger.load_payload(str(workout_path))
            if not any((rows, bodyweight, css, sleep, nutrition)):
                raise ValueError(f'Empty workout payload: {workout_path}')
            print(f'{person} | workout: {workout_path} ({len(rows)} rows)')
            status = logger.write_payload(person, rows, bodyweight, css, sleep=sleep,
                                          nutrition_phase=nutrition, dry_run=True)
            for line in status:
                print(f'  {line}')
            if any(line.startswith('WARN:') for line in status):
                raise ValueError(f'Workout conflicts for {person}; review before applying')
            if any((bodyweight, css, sleep, nutrition)):
                print('  Other payload categories have basic structure/date checks only; conflicts and values are not fully previewed.')
        prepared.append((person, export_path, workout_path))
    return prepared


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--entry', nargs=3, action='append', required=True,
                        metavar=('PERSON', 'EXPORT', 'WORKOUT_JSON'))
    parser.add_argument('--apply', action='store_true', help='Apply after preflight')
    parser.add_argument('--allow-past-months', action='store_true')
    args = parser.parse_args()
    try:
        entries = preflight(args.entry)
    except (OSError, ValueError, TypeError, KeyError, EmptyImportError) as exc:
        print(f'Preflight failed: {exc}', file=sys.stderr)
        return 1
    if not args.apply:
        print('Preview only; no files were changed.')
        return 0
    sys.stdout.flush()
    # Use the public CLIs so their validation, history and import policy remain
    # the single source of truth. Earlier writes are not rolled back on failure.
    for person, export, workout in entries:
        commands = []
        if workout:
            commands.append([sys.executable, str(LOGGER), '--person', person, str(workout)])
        if export:
            cmd = [sys.executable, str(IMPORTER), '--person', person, '--export', str(export)]
            if args.allow_past_months:
                cmd.append('--allow-past-months')
            commands.append(cmd)
        for cmd in commands:
            result = subprocess.run(cmd, check=False)
            if result.returncode:
                print(f'Stopped at {person}; earlier writes may have completed.', file=sys.stderr)
                return result.returncode
    return 0


if __name__ == '__main__':
    sys.exit(main())
