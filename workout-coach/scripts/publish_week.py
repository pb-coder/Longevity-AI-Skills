"""Validate and publish one structured weekly prescription."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from workout_coach.lib.weekly_prescription import PublishError, publish_week


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--person', required=True)
    parser.add_argument('--tracker', required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--draft', help='Path to a complete weekly draft')
    source.add_argument('--amend', help='Path to a JSON object with replacement sessions')
    args = parser.parse_args(argv)
    try:
        tracker = json.loads(Path(args.tracker).read_text(encoding='utf-8'))
        draft = json.loads(Path(args.draft or args.amend).read_text(encoding='utf-8'))
        print(json.dumps(publish_week(args.person, draft, tracker, amend=args.amend is not None)))
        return 0
    except PublishError as exc:
        print(json.dumps({'error': str(exc), 'kind': exc.kind, 'issues': exc.issues}), file=sys.stderr)
        return 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        kind = "io_error" if isinstance(exc, OSError) else "invalid_input"
        print(json.dumps({'error': str(exc), 'kind': kind}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
