import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import branch_state as local_state
from core import Ticket


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


class LocalStateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.repo = Path(self.folder.name) / "repo"
        self.repo.mkdir()
        self.tickets = Path(self.folder.name) / "tickets"
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "test@example.invalid")
        git(self.repo, "config", "user.name", "Test")
        (self.repo / "README").write_text("x\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "base")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.repo, "checkout", "-qb", "feature/APP-42")

    def tearDown(self):
        self.folder.cleanup()

    def state(self):
        with patch.dict(os.environ, {"SIDEQUEST_TICKETS_DIR": str(self.tickets)}):
            return local_state.branch_state(str(self.repo), "APP-42")

    def test_counts_unpushed_uncommitted_and_behind_and_needs_qa_for_ui_changes(self):
        (self.repo / "app" / "views").mkdir(parents=True)
        (self.repo / "app" / "views" / "a.html.erb").write_text("<p>a</p>\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "view")
        (self.repo / "notes.txt").write_text("draft\n")
        git(self.repo, "checkout", "-q", "main")
        (self.repo / "other").write_text("y\n")
        git(self.repo, "add", "other")
        git(self.repo, "commit", "-qm", "main moved")
        git(self.repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.repo, "checkout", "-q", "feature/APP-42")
        state = self.state()
        self.assertEqual((state["unpushed"], state["upstream"], state["uncommitted"], state["behind"]), (1, False, 1, 1))
        self.assertEqual(state["ui_files"], ["app/views/a.html.erb"])
        self.assertEqual(state["qa"], "missing")
        self.assertEqual(local_state.summary(state),
                         "Local 1 commit not pushed · 1 uncommitted · 1 behind main · QA shots missing")

    def test_clean_branch_without_ui_changes(self):
        state = self.state()
        self.assertEqual(state["qa"], "not needed")
        self.assertEqual(local_state.summary(state), "Local clean · up to date with main")

    def test_missing_folder_is_reported_not_guessed(self):
        state = local_state.branch_state(str(Path(self.folder.name) / "gone"), "APP-42")
        self.assertEqual(local_state.summary(state), "Local state unavailable")

    def test_qa_hint_only_for_my_tickets_with_missing_or_stale_shots(self):
        mine, theirs = Ticket("APP-42", lane="Needs me"), Ticket("APP-43", lane="Waiting")
        for qa, ticket, expected in (("missing", mine, "QA shots missing: Space s → QA locally"),
                                     ("stale", mine, "QA shots stale: Space s → QA locally"),
                                     ("current", mine, ""), ("not needed", mine, ""),
                                     ("missing", theirs, "")):
            with self.subTest(qa=qa, lane=ticket.lane):
                self.assertEqual(local_state.qa_hint(ticket, {"qa": qa}), expected)
        self.assertEqual(local_state.qa_hint(mine, None), "")


class AppWiringTests(unittest.TestCase):
    def test_worktrees_start_the_branch_check_and_overview_and_card_show_it(self):
        import time
        from core import Store
        from tui import App
        store = Store(":memory:")
        self.addCleanup(store.close)
        with tempfile.TemporaryDirectory() as folder:
            app = App(store, Path(folder), demo=True)
        app.demo = False
        state = {"uncommitted": 2, "unpushed": 0, "upstream": True, "behind": 0, "ui_files": ["app/views/a.erb"],
                 "qa": "missing", "qa_reason": ""}
        with patch("branch_state.collect", return_value={"DEMO-901": state}) as collect, \
                patch("tui.worktrees", return_value={}), patch.object(App, "refresh_worklog"):
            app.events.put(("worktrees", {"DEMO-901": "/wt/DEMO-901"}))
            app.drain()
            deadline = time.monotonic() + 3
            while app.jobs and time.monotonic() < deadline:
                app.drain()
                time.sleep(0.01)
            app.drain()
        self.assertEqual(collect.call_args[0][0].get("DEMO-901"), "/wt/DEMO-901")
        ticket = next(t for t in app.tickets if t.key == "DEMO-901")
        app.detail_tab = "Overview"
        self.assertIn("Local 2 uncommitted · QA shots missing", app.details(ticket))
        self.assertIn("Local 2 uncommitted · QA shots missing", app.summary_card(ticket))


if __name__ == "__main__":
    unittest.main()
