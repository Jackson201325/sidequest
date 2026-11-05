import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "bin/sidequest-worktree.py"


CLEAN_ENV = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}   # a commit hook exports GIT_INDEX_FILE


def git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd, check=True,
                   capture_output=True, env=CLEAN_ENV)


class WorktreeLookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.remote, self.repo = root / "remote.git", root / "repo"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True, env=CLEAN_ENV)
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.rb").write_text("x = 1\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        git(self.repo, "remote", "add", "origin", str(self.remote))
        git(self.repo, "push", "-q", "origin", "main")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def lookup(self, target, *flags):
        result = subprocess.run([sys.executable, str(SCRIPT), target, *flags], cwd=self.repo,
                                text=True, capture_output=True, env=CLEAN_ENV)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def state(self, target):
        return json.loads(self.lookup(target, "--json"))

    def test_nothing_exists(self):
        self.assertEqual(self.state("DEMO-9")["state"], "none")
        self.assertEqual(self.lookup("DEMO-9").splitlines()[0], "DEMO-9: none")

    def test_a_worktree_for_the_ticket_wins_and_reports_its_path_and_branch(self):
        folder = self.root / "DEMO-9-orders"
        git(self.repo, "worktree", "add", "-q", "-b", "feature/DEMO-9-orders", str(folder))
        found = self.state("demo-9")
        self.assertEqual((found["state"], found["branch"], Path(found["path"]).resolve()),
                         ("worktree", "feature/DEMO-9-orders", folder.resolve()))
        self.assertEqual(self.lookup("DEMO-9").splitlines()[:3],
                         ["DEMO-9: worktree", "PATH " + found["path"], "BRANCH feature/DEMO-9-orders"])

    def test_the_main_checkout_on_the_ticket_branch_is_reported_as_such(self):
        git(self.repo, "checkout", "-qb", "fix/DEMO-10-totals")
        found = self.state("DEMO-10")
        self.assertEqual((found["state"], found["branch"]), ("main-checkout", "fix/DEMO-10-totals"))
        self.assertEqual(Path(found["path"]).resolve(), self.repo.resolve())

    def test_a_branch_without_a_worktree_is_branch_only_local_or_remote(self):
        git(self.repo, "branch", "feature/DEMO-11-local")
        self.assertEqual(self.state("DEMO-11")["state"], "branch-only")
        git(self.repo, "branch", "feature/DEMO-12-remote")
        git(self.repo, "push", "-q", "origin", "feature/DEMO-12-remote")
        git(self.repo, "branch", "-q", "-D", "feature/DEMO-12-remote")
        found = self.state("DEMO-12")
        self.assertEqual((found["state"], found["branch"]), ("branch-only", "feature/DEMO-12-remote"))

    def test_similar_keys_and_backup_branches_do_not_match(self):
        for name in ("feature/DEMO-61-other", "feature/DEMO-616-other", "backup/DEMO-6-old", "backup/DEMO-6"):
            git(self.repo, "branch", name)
        self.assertEqual(self.state("DEMO-6")["state"], "none")
        self.assertEqual(self.state("DEMO-61")["branch"], "feature/DEMO-61-other")

    def test_a_branch_name_finds_its_worktree_for_pr_feedback(self):
        folder = self.root / "DEMO-13-x"
        git(self.repo, "worktree", "add", "-q", "-b", "feature/DEMO-13-x", str(folder))
        found = self.state("feature/DEMO-13-x")
        self.assertEqual((found["state"], Path(found["path"]).resolve()), ("worktree", folder.resolve()))
        self.assertEqual(self.state("feature/DEMO-99-nope")["state"], "none")

    def test_outside_a_git_repository_is_an_error(self):
        with tempfile.TemporaryDirectory() as plain:
            result = subprocess.run([sys.executable, str(SCRIPT), "DEMO-9"], cwd=plain, text=True, capture_output=True, env=CLEAN_ENV)
            self.assertEqual(result.returncode, 1)
            self.assertIn("not a git repository", result.stderr)


if __name__ == "__main__":
    unittest.main()
