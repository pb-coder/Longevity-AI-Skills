"""Version each person's ``data/`` directory as its own git repository.

The CSVs are the tracker's record, and until now nothing kept their
history: a bad import or a mis-parsed ``/log`` overwrote cells with no way
back except the archived source exports. A commit per write turns that
into an ordinary revert.

``<Person>/`` sits *outside* the ``Skills/`` repo, so a repo at
``<Person>/data`` nests inside nothing and conflicts with nothing.

**These repos live in iCloud Drive.** That was a deliberate call — the
tracker has to be readable from every device the user logs from — and it
comes with one real hazard: iCloud syncs the ``.git`` directory like any
other folder, so two machines writing at once can interleave objects and
refs. Three guards follow from that, all of them enforced here or in the
``.gitignore`` this module writes:

1. Conflict copies (``file 2.csv``) are ignored, so a sync artifact never
   lands in a commit and never becomes the file a later read picks up.
2. **No automatic ``git gc`` or repacking, ever.** Repacking rewrites many
   objects at once and is the operation most likely to lose a race with a
   sync. Nothing in this module runs it.
3. One machine at a time. That one cannot be enforced in code; it is
   stated in ``Skills/CLAUDE.md``.

A git failure must never fail a workout log. Every entry point catches,
warns, and returns ``None`` — losing the history of a write is an
annoyance, losing the write is not acceptable.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .person_paths import data_dir

__all__ = ["commit_data", "GIT_IDENTITY_NAME", "GIT_IDENTITY_EMAIL"]

# Set locally on every repo this module initialises. Committing must not
# depend on the machine's global git config being present or sane — a
# fresh laptop with no ``user.email`` would otherwise fail every write.
GIT_IDENTITY_NAME = "Workout Tracker"
GIT_IDENTITY_EMAIL = "tracker@localhost"

# Mirrors Skills/.gitignore. The iCloud conflict patterns matter more here
# than they do there: a conflict copy inside a data repo is exactly how a
# tracker directory gets polluted with a stale duplicate of a live CSV.
GITIGNORE = """\
.DS_Store
__pycache__/
*.pyc

# iCloud Drive "Documents in the Cloud" conflict copies.
# Pattern: when two devices both have edits, iCloud appends " 2", " 3", ...
# to the duplicate filename instead of merging. A conflict copy inside a
# data repo is how a stale duplicate of a live CSV gets committed.
* [0-9].*
* [0-9][0-9].*
* [0-9]
* [0-9]/**
* [0-9][0-9]
* [0-9][0-9]/**
"""


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=True,
    )


def _ensure_repo(repo: Path) -> None:
    """Initialise ``repo`` as a git repository if it is not one already.

    Identity is set locally rather than relied on globally, and the
    ignore file is written on init only — a user edit to it afterwards
    is theirs to keep.
    """
    if (repo / ".git").exists():
        return
    _run(repo, "init", "-q")
    _run(repo, "config", "user.name", GIT_IDENTITY_NAME)
    _run(repo, "config", "user.email", GIT_IDENTITY_EMAIL)
    gitignore = repo / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(GITIGNORE, encoding="utf-8")


def commit_data(person: str, message: str) -> str | None:
    """Stage and commit everything under ``<person>/data/``.

    Returns the new commit's short SHA, or ``None`` when there was
    nothing to commit or anything went wrong. One call is one commit:
    a ``/log`` run or an import is a single atomic change to the tracker
    and should read as a single entry in the history, not as one commit
    per touched CSV.

    Never raises. A tracker whose git state is broken still logs
    workouts; it just stops recording their history until someone looks.
    """
    try:
        repo = data_dir(person)
        if not repo.exists():
            return None
        _ensure_repo(repo)
        _run(repo, "add", "-A", ".")
        status = _run(repo, "status", "--porcelain")
        if not status.stdout.strip():
            return None  # clean tree: a no-op write must not create an empty commit
        _run(repo, "commit", "-q", "-m", message)
        return _run(repo, "rev-parse", "--short", "HEAD").stdout.strip()
    except (OSError, subprocess.CalledProcessError) as e:
        detail = getattr(e, "stderr", "") or str(e)
        print(
            f"WARN: could not commit {person} data ({str(detail).strip()[:200]})",
            file=sys.stderr,
        )
        return None
