"""Regressions from the Nov 2026 code review: false ticket keys, QA rework, stuck refresh, worktree parsing."""
import queue
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from core import Ticket, infer, ticket_key, tickets_from
from workflow import stage_context
import tui


class TicketKeyTests(unittest.TestCase):
    def test_lowercase_words_are_not_keys_without_known_projects(self):
        self.assertIsNone(ticket_key("Upgrade to utf-8 handling"))
        self.assertIsNone(ticket_key("chore/python-3-bump"))
        self.assertEqual(ticket_key("fix/APP-42-stock"), "APP-42")

    def test_known_projects_accept_any_case_and_reject_other_prefixes(self):
        self.assertEqual(ticket_key("feature/trd-12-totals", {"TRD"}), "TRD-12")
        self.assertIsNone(ticket_key("Bump PYTHON-3 image", {"TRD"}))
        self.assertEqual(ticket_key("PYTHON-3 then TRD-7", {"TRD"}), "TRD-7")

    def test_pr_title_does_not_create_a_phantom_ticket(self):
        jira = {"tickets": [{"key": "APP-1", "summary": "Real"}]}
        prs = {"open_prs": [{"number": 5, "ticket": "PYTHON-3", "title": "Bump python 3.12 base image",
                             "branch": "chore/python-3-bump"}]}
        self.assertEqual(sorted(t.key for t in tickets_from(jira, prs)), ["APP-1", "PR-5"])

    def test_branch_key_wins_over_a_bogus_title_match(self):
        prs = {"open_prs": [{"number": 6, "ticket": "PYTHON-3", "title": "Python 3 fixes", "branch": "fix/app-9-py3"}]}
        self.assertEqual([t.key for t in tickets_from({}, prs, projects=["APP"])], ["APP-9"])


class QaReworkTests(unittest.TestCase):
    def test_qa_failed_assigned_to_me_needs_me(self):
        court, action, _ = infer(Ticket("APP-1", status="QA Failed", assigned_me=True, assignee="Me"))
        self.assertEqual((court, action), ("me", "Address returned work"))

    def test_qa_failed_assigned_elsewhere_is_not_waiting_for_qa(self):
        ticket = Ticket("APP-2", status="QA Failed", assigned_me=False, assignee="Dev Two")
        court, action, _ = infer(ticket)
        self.assertEqual((court, action), ("them", "Waiting for Jira assignee"))
        ticket.court = court
        self.assertEqual(stage_context(ticket)["name"], "Build")

    def test_real_qa_and_unmapped_qa_statuses_still_wait_for_qa(self):
        for status in ("QA", "Ready for QA", "UAT QA pending"):
            with self.subTest(status=status):
                self.assertEqual(infer(Ticket("APP-3", status=status, assigned_me=False))[1], "Waiting for QA result")


class WorkerTests(unittest.TestCase):
    def app(self):
        app = tui.App.__new__(tui.App)
        app.events, app.jobs, app.refreshing, app.demo, app.dirty = queue.Queue(), {}, False, False, False
        app.snapshots = Path("/nonexistent")
        return app

    def drain(self, app, until):
        deadline, seen = time.monotonic() + 5, []
        while time.monotonic() < deadline:
            try:
                seen.append(app.events.get(timeout=0.1))
            except queue.Empty:
                continue
            if seen[-1][0] == until:
                return seen
        self.fail("worker never finished: %r" % seen)

    def test_refresh_always_finishes_on_an_unexpected_error(self):
        app = self.app()
        with patch.object(tui, "run", side_effect=KeyError("sources")):
            app.refresh()
            events = self.drain(app, "done")
        self.assertIn("failed unexpectedly", events[-1][1][0])

    def test_background_job_reports_an_unexpected_error(self):
        app = self.app()
        app.background("worklog", "Loading dated work history", lambda: {}["missing"], "worklog")
        events = self.drain(app, "job_done")
        self.assertEqual(events[0][0], "message")
        self.assertIn("Loading dated work history failed unexpectedly", events[0][1])


class WorktreeTests(unittest.TestCase):
    def test_backup_branches_and_lowercase_keys(self):
        porcelain = ("worktree /repo\nHEAD 1\nbranch refs/heads/main\n\n"
                     "worktree /wt/app-7\nHEAD 2\nbranch refs/heads/feature/APP-7-totals\n\n"
                     "worktree /wt/backup\nHEAD 3\nbranch refs/heads/backup/APP-7-old\n\n")
        with patch.object(tui.config, "get", return_value="/repo"), patch.object(tui, "run", return_value=porcelain):
            self.assertEqual(tui.worktrees(), {"APP-7": "/wt/app-7"})


if __name__ == "__main__":
    unittest.main()
