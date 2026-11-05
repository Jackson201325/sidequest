import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from core import Ticket
from activity import ticket_activity
from worklog import collect_worklog, daily_summary


class WorklogTests(unittest.TestCase):
    def test_branch_association_captures_commits_without_ticket_in_subject(self):
        first = "abc\x1f2026-10-26T22:00:00-03:00\x1fDEMO-42 Fix quantities\x1e"
        branch = first + "def\x1f2026-10-27T11:00:00-03:00\x1fAdd quantity validation\x1e"
        calls = []

        def run(args, **kwargs):
            calls.append(args)
            return branch if "origin/main..HEAD" in args else first

        result = collect_worklog([{"key": "DEMO-42", "worktree": "/tmp/DEMO-42"}], Path("/tmp/repo"), run)
        self.assertEqual(len(result["entries"]["DEMO-42"]), 2)
        self.assertEqual(result["entries"]["DEMO-42"][0]["subject"], "Add quantity validation")
        self.assertTrue(all("--author=Example Developer" in cmd for cmd in calls))

    def test_summary_deduplicates_git_and_pr_and_groups_by_local_date(self):
        ticket = Ticket("DEMO-42", prs=[{"commits": [
            {"oid": "abc", "authoredDate": "2026-10-27T01:00:00Z", "messageHeadline": "Add validation",
             "authors": [{"login": "example-developer"}]},
            {"oid": "other", "authoredDate": "2026-10-27T01:00:00Z", "messageHeadline": "Other person's work",
             "authors": [{"login": "reviewer"}]},
        ]}])
        commits = [{"sha": "abc", "date": "2026-10-27T01:00:00Z", "subject": "Add validation", "source": "git"}]
        output = "\n".join(daily_summary(ticket, commits))
        self.assertIn("26 Oct 2026", output)
        self.assertEqual(output.count("Add validation"), 1)
        self.assertNotIn("Other person's work", output)

    def test_activity_shows_full_github_comments_with_author_and_location(self):
        ticket = Ticket("DEMO-42", prs=[{"number": 42, "discussion": [
            {"author": {"login": "reviewer"}, "createdAt": "2026-01-02T15:00:00Z", "body": "Please verify quantities before QA."}
        ], "unresolved": [{"path": "app/models/order.rb", "line": 7, "comments": [
            {"author": "reviewer", "created_at": "2026-01-02T15:00:00Z", "body": "Reject negative quantities."}
        ]}]}])
        events = ticket_activity(ticket)
        self.assertIn(("PR #42 discussion comment", "Please verify quantities before QA.", "reviewer"),
                      [(e["title"], e["body"], e["author"]) for e in events])
        self.assertIn(("PR #42 inline comment · app/models/order.rb:7", "Reject negative quantities.", "reviewer"),
                      [(e["title"], e["body"], e["author"]) for e in events])


class FeedbackHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from sidequest import github
        cls.module = github

    def test_activity_is_opt_in_and_includes_discussion_review_and_commits(self):
        pr = {"number": 42, "title": "DEMO-42 Fix quantities", "comments": [{"body": "Check totals"}],
              "reviews": [{"body": "Looks good"}], "commits": [{"oid": "abc"}]}
        compact = self.module.enrich_pr(pr, include_threads=False)
        with patch.object(self.module, 'activity_for_pr', return_value={'discussion': pr['comments'],
                          'reviews': pr['reviews'], 'commits': pr['commits']}):
            full = self.module.enrich_pr(pr, include_threads=False, include_activity=True)
        self.assertNotIn("discussion", compact)
        self.assertEqual(full["discussion"][0]["body"], "Check totals")
        self.assertEqual(full["commits"][0]["oid"], "abc")

    def test_activity_failures_cannot_erase_cached_prs(self):
        with patch.object(self.module.tr, "run_command", return_value=""):
            with self.assertRaises(RuntimeError):
                self.module.list_open_prs(include_activity=True)
            with self.assertRaises(RuntimeError):
                self.module.list_open_prs()


if __name__ == "__main__":
    unittest.main()
