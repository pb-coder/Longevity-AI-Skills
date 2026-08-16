"""Per-person data repositories: init, commit, no-op, and failure.

The contract that matters most is the last one. These repos exist so a
bad import can be reverted; they must never be the reason a workout
fails to log. Every path through ``commit_data`` returns rather than
raises.
"""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

from shared import data_git, person_paths


class DataGitTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_root = person_paths.WORKOUT_TRACKER_ROOT
        person_paths.WORKOUT_TRACKER_ROOT = Path(self._tmp.name)
        self.data = person_paths.ensure_data_dir("Test")

    def tearDown(self) -> None:
        person_paths.WORKOUT_TRACKER_ROOT = self._old_root
        self._tmp.cleanup()

    def _write(self, name: str, text: str) -> None:
        (self.data / name).write_text(text, encoding="utf-8")

    def _git(self, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=str(self.data),
            capture_output=True, text=True, check=True,
        ).stdout.strip()


class InitTests(DataGitTestCase):
    def test_first_commit_initialises_the_repository(self) -> None:
        self.assertFalse((self.data / ".git").exists())
        self._write("health_metrics.csv", "Date,Notes\n2026-08-15,\n")
        sha = data_git.commit_data("Test", "import: first")
        self.assertIsNotNone(sha)
        self.assertTrue((self.data / ".git").is_dir())
        self.assertEqual(self._git("log", "-1", "--pretty=%s"), "import: first")

    def test_identity_is_set_locally_so_global_config_is_irrelevant(self) -> None:
        self._write("health_metrics.csv", "Date\n2026-08-15\n")
        data_git.commit_data("Test", "import: first")
        self.assertEqual(self._git("config", "--local", "user.name"),
                         data_git.GIT_IDENTITY_NAME)
        self.assertEqual(self._git("config", "--local", "user.email"),
                         data_git.GIT_IDENTITY_EMAIL)

    def test_icloud_conflict_copies_are_ignored(self) -> None:
        """A conflict copy inside the repo is how a data dir gets polluted."""
        self._write("health_metrics.csv", "Date\n2026-08-15\n")
        data_git.commit_data("Test", "import: first")
        self._write("health_metrics 2.csv", "Date\n2026-01-01\n")
        self._write(".DS_Store", "junk")
        self.assertIsNone(data_git.commit_data("Test", "import: second"))
        tracked = self._git("ls-files")
        self.assertIn("health_metrics.csv", tracked)
        self.assertNotIn("health_metrics 2.csv", tracked)
        self.assertNotIn(".DS_Store", tracked)

    def test_a_user_edited_gitignore_is_left_alone(self) -> None:
        (self.data / ".gitignore").write_text("mine\n", encoding="utf-8")
        self._write("health_metrics.csv", "Date\n2026-08-15\n")
        data_git.commit_data("Test", "import: first")
        self.assertEqual((self.data / ".gitignore").read_text(), "mine\n")


class CommitTests(DataGitTestCase):
    def setUp(self) -> None:
        super().setUp()
        self._write("health_metrics.csv", "Date\n2026-08-15\n")
        self.first = data_git.commit_data("Test", "import: first")

    def test_a_clean_tree_makes_no_empty_commit(self) -> None:
        self.assertIsNone(data_git.commit_data("Test", "log: nothing changed"))
        self.assertEqual(self._git("rev-list", "--count", "HEAD"), "1")

    def test_a_changed_tree_commits_and_returns_the_short_sha(self) -> None:
        self._write("health_metrics.csv", "Date\n2026-08-16\n")
        sha = data_git.commit_data("Test", "log: 3 rows, 2026-08-16")
        self.assertIsNotNone(sha)
        self.assertNotEqual(sha, self.first)
        self.assertEqual(sha, self._git("rev-parse", "--short", "HEAD"))
        self.assertEqual(self._git("log", "-1", "--pretty=%s"), "log: 3 rows, 2026-08-16")

    def test_one_operation_is_one_commit_across_many_files(self) -> None:
        """A /log run is one atomic change, not one commit per CSV."""
        self._write("health_metrics.csv", "Date\n2026-08-16\n")
        self._write("workout_sessions.csv", "Date\n2026-08-16\n")
        (self.data / "monthly").mkdir(exist_ok=True)
        (self.data / "monthly" / "2026.08.csv").write_text("Date\n", encoding="utf-8")
        data_git.commit_data("Test", "log: 5 rows, 2026-08-16")
        self.assertEqual(self._git("rev-list", "--count", "HEAD"), "2")
        touched = self._git("show", "--name-only", "--pretty=", "HEAD").split("\n")
        self.assertEqual(len(touched), 3)

    def test_nested_directories_are_staged(self) -> None:
        (self.data / "sleep").mkdir(exist_ok=True)
        (self.data / "sleep" / "2026.08.nights.csv").write_text("Date\n", encoding="utf-8")
        data_git.commit_data("Test", "import: nights")
        self.assertIn("sleep/2026.08.nights.csv", self._git("ls-files"))


class FailureTests(DataGitTestCase):
    """A git failure must cost the history of a write, never the write."""

    def test_a_git_failure_warns_and_returns_none_instead_of_raising(self) -> None:
        self._write("health_metrics.csv", "Date\n2026-08-15\n")
        boom = subprocess.CalledProcessError(1, ["git"], stderr="fatal: forced failure")
        err = StringIO()
        with mock.patch.object(data_git, "_run", side_effect=boom):
            with redirect_stderr(err):
                self.assertIsNone(data_git.commit_data("Test", "log: doomed"))
        self.assertIn("could not commit", err.getvalue())

    def test_an_os_error_is_swallowed_too(self) -> None:
        self._write("health_metrics.csv", "Date\n2026-08-15\n")
        with mock.patch.object(data_git, "_run", side_effect=OSError("git not found")):
            with redirect_stderr(StringIO()):
                self.assertIsNone(data_git.commit_data("Test", "log: doomed"))

    def test_a_person_with_no_data_directory_is_a_quiet_no_op(self) -> None:
        with redirect_stderr(StringIO()):
            self.assertIsNone(data_git.commit_data("Nobody", "log: nothing"))

    def test_nothing_ever_runs_a_repack(self) -> None:
        """gc/repack is the operation most likely to lose an iCloud race."""
        source = Path(data_git.__file__).read_text(encoding="utf-8")
        for forbidden in ('"gc"', '"repack"', '"prune"', "--aggressive"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
