"""Validate and publish one structured weekly prescription."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from workout_coach.lib.weekly_prescription import publish_week


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--person', required=True)
    parser.add_argument('--tracker', required=True)
    parser.add_argument('--draft', required=True)
    args = parser.parse_args(argv)
    try:
        tracker = json.loads(Path(args.tracker).read_text(encoding='utf-8'))
        draft = json.loads(Path(args.draft).read_text(encoding='utf-8'))
        print(json.dumps(publish_week(args.person, draft, tracker)))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'error': str(exc)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
