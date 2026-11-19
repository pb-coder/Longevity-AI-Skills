#!/usr/bin/env python3
"""Validate and save an explicitly supplied private coach profile JSON."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workout_coach.lib.exercise_fit import save_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--person', required=True)
    parser.add_argument('profile', type=Path, help='JSON profile to save')
    args = parser.parse_args()
    try:
        profile = json.loads(args.profile.read_text(encoding='utf-8'))
        save_profile(args.person, profile)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print('Coach profile saved.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
