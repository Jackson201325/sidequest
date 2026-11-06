"""Regressions from the Nov 2026 code review: false ticket keys, QA rework, stuck refresh, worktree parsing."""
import json
import queue
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from core import Store, Ticket, infer, ticket_key, tickets_from
from queue_evidence import EVERY, QueueEvidence
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

    def test_rework_statuses_match_after_normalising(self):
        for status in ("QA_Failed", "QA  Failed", "Fixing Revisions"):
            with self.subTest(status=status):
                self.assertEqual(infer(Ticket("APP-1", status=status, assigned_me=True))[1], "Address returned work")

    def test_pr_titles_never_create_lowercase_phantom_tickets_without_projects(self):
        prs = {"open_prs": [{"number": 5, "title": "Bump python 3.12 base image", "branch": "chore/python-3-bump"}]}
        self.assertEqual([t.key for t in tickets_from({}, prs)], ["PR-5"])

    def test_real_qa_and_unmapped_qa_statuses_still_wait_for_qa(self):
        for status in ("QA", "Ready for QA", "UAT QA pending"):
            with self.subTest(status=status):
                self.assertEqual(infer(Ticket("APP-3", status=status, assigned_me=False))[1], "Waiting for QA result")


class WorkerTests(unittest.TestCase):
    def app(self):
        app = tui.App.__new__(tui.App)
        app.events, app.jobs, app.refreshing, app.demo, app.dirty = queue.Queue(), {}, False, False, False
        store = Store(":memory:")
        self.addCleanup(store.close)
        app.evidence = QueueEvidence(store, Path("/nonexistent"))
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
            events = self.drain(app, "refreshed")
        updates, messages, failed = events[-1][1]
        self.assertIn("failed unexpectedly", messages[0])
        self.assertEqual((updates, failed), ({}, {EVERY}))

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

    def test_only_branch_segment_keys_map_a_worktree_like_lookup(self):
        porcelain = ("worktree /repo\nHEAD 1\nbranch refs/heads/main\n\n"
                     "worktree /wt/a\nHEAD 2\nbranch refs/heads/feature/APP-1-revert-APP-2\n\n"
                     "worktree /wt/b\nHEAD 3\nbranch refs/heads/fix/APP-3-utf-8\n\n")
        with patch.object(tui.config, "get", return_value="/repo"), patch.object(tui, "run", return_value=porcelain):
            self.assertEqual(tui.worktrees(), {"APP-1": "/wt/a", "APP-3": "/wt/b"})


class FirstRunTests(unittest.TestCase):
    """Found by the fresh-install e2e run on Python 3.9."""

    def test_jira_offsets_without_a_colon_parse_on_every_supported_python(self):
        from sidequest.evidence import parse_time
        stamp = parse_time("2026-11-04T10:35:58.000+0000")
        self.assertIsNotNone(stamp)
        self.assertEqual(stamp.utcoffset().total_seconds(), 0)
        self.assertEqual(parse_time("2026-11-04T07:35:58-0300"), parse_time("2026-11-04T10:35:58Z"))

    def test_jira_comments_and_updates_reach_the_activity_tab(self):
        from activity import ticket_activity
        ticket = Ticket("APP-43", updated="2026-11-04T10:00:00.000+0000",
                        jira_comments=[{"author": "Rae", "body": "Off by a cent",
                                        "created_at": "2026-11-04T10:35:58.000+0000",
                                        "updated_at": "2026-11-04T10:35:58.000+0000"}])
        self.assertEqual([e["title"] for e in ticket_activity(ticket)], ["Comment added", "Ticket updated"])

    def test_first_run_errors_name_the_missing_piece(self):
        from sidequest.access import failure_for
        gh = str(failure_for("GitHub", "[Errno 2] No such file or directory: 'gh'"))
        self.assertIn("GitHub CLI (gh) is not installed", gh)
        jira = str(failure_for("Jira", "No Jira credentials: configure jira.email and set SIDEQUEST_JIRA_TOKEN"))
        self.assertIn("no credentials yet", jira)
        self.assertNotIn("expired", jira)
        self.assertIn("login unavailable or expired", str(failure_for("Jira", "Jira HTTP 401; previous data retained")))

    def test_header_marks_unconfigured_and_failed_sources(self):
        app = tui.App.__new__(tui.App)
        app.refreshing, app.jobs, app.sort_descending, app.sort_mode, app.styles = False, {}, True, "Attention", {}
        store = Store(":memory:")
        self.addCleanup(store.close)
        app.evidence = QueueEvidence(store, Path("/nonexistent"))
        app.evidence.jira = {"enabled": False, "generated_at": tui.now().isoformat()}
        app.evidence.prs = {"enabled": True, "generated_at": tui.now().isoformat()}
        text = app.header_status()[0]
        self.assertIn("Jira off", text)
        self.assertNotIn("STALE", text)
        app.evidence.finish_refresh(({}, ["GitHub: request failed. Previous data retained."], {"prs"}))
        self.assertIn("GitHub failed, data now", app.header_status()[0])

    def test_header_marks_every_kind_of_refresh_failure(self):
        app = tui.App.__new__(tui.App)
        app.refreshing, app.jobs, app.sort_descending, app.sort_mode, app.styles = False, {}, True, "Attention", {}
        store = Store(":memory:")
        self.addCleanup(store.close)
        app.evidence = QueueEvidence(store, Path("/nonexistent"))
        fresh = {"enabled": True, "jira_available": True, "tickets": [], "open_prs": []}

        def timed_out(args, timeout):
            raise OSError("Command timed out after 300 seconds")
        cases = {"rejected Jira": (lambda args, timeout: json.dumps({"sources": {"prs": fresh, "jira": {}}}), ("Jira failed",)),
                 "unconfigured Jira": (lambda args, timeout: json.dumps({"sources": {"prs": fresh}, "failures": {
                     "jira": "Jira is not configured; configure jira.site. Previous data retained."}}), ("Jira failed",)),
                 "timed-out run": (timed_out, ("Jira failed", "GitHub failed"))}
        for case, (run, expected) in cases.items():
            with self.subTest(case=case):
                app.evidence.jira = app.evidence.prs = dict(fresh, generated_at=tui.now().isoformat())
                app.evidence.finish_refresh(app.evidence.collect(run))
                text = app.header_status()[0]
                for marker in expected:
                    self.assertIn(marker, text)
                if len(expected) == 1:
                    self.assertNotIn("GitHub failed", text)

    def test_refresh_names_rejected_sources_as_the_header_does(self):
        worker = WorkerTests()
        worker.addCleanup = self.addCleanup
        app = worker.app()
        data = json.dumps({"sources": {"jira": {"tickets": []}, "prs": {"open_prs": "bad"}}, "failures": {}})
        with patch.object(tui, "run", return_value=data):
            app.refresh()
            events = worker.drain(app, "refreshed")
        _, messages, failed = events[-1][1]
        self.assertEqual(messages, ["Jira unavailable; keeping previous data", "GitHub unavailable; keeping previous data"])
        self.assertEqual(failed, {"jira", "prs"})


if __name__ == "__main__":
    unittest.main()
