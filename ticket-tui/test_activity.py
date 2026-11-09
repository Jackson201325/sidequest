import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from activity import ticket_activity
from core import Ticket


class ActivityTests(unittest.TestCase):
    def test_only_jira_and_github_events_are_in_the_log(self):
        ticket = Ticket("DEMO-42", updated="2026-10-26T12:00:00Z", jira_comments=[{
            "author": "Reviewer", "update_author": "Reviewer", "body": "Please verify totals",
            "created_at": "2026-10-26T10:00:00Z", "updated_at": "2026-10-27T10:00:00Z",
        }], prs=[{"number": 42, "reviews": [{"author": {"login": "reviewer"}, "state": "APPROVED", "submittedAt": "2026-10-27T11:00:00Z"}],
                  "commits": [{"oid": "abc", "authoredDate": "2026-10-25T12:00:00Z", "messageHeadline": "Fix totals"},
                              {"oid": "abc", "authoredDate": "2026-10-25T12:00:00Z", "messageHeadline": "Fix totals"}]}])
        ticket.local = {"last_local_activity_at": "2026-10-27T13:00:00Z", "progress_at": "2026-10-27T13:00:00Z"}
        events = ticket_activity(ticket)
        self.assertEqual({e["source"] for e in events}, {"Jira", "GitHub"})
        self.assertEqual(events[0]["title"], "PR #42 review: approved")
        self.assertEqual(sum("commit" in e["title"].lower() for e in events), 1)
        self.assertTrue(any(e["title"] == "Comment edited" for e in events))

    def test_empty_commented_review_is_merged_into_its_line_comments_or_explained(self):
        inline = {"path": "app/models/order.rb", "line": 7, "comments": [
            {"author": "reviewer", "created_at": "2026-10-27T11:00:00Z", "body": "Use filter_map here"}]}
        wrapper = {"author": {"login": "reviewer"}, "state": "COMMENTED", "body": "", "submittedAt": "2026-10-27T11:00:30Z"}
        loaded = ticket_activity(Ticket("DEMO-42", prs=[{"number": 42, "reviews": [wrapper], "unresolved": [inline]}]))
        self.assertEqual([e["title"] for e in loaded], ["PR #42 inline comment · app/models/order.rb:7"])
        resolved = ticket_activity(Ticket("DEMO-42", prs=[{"number": 42, "reviews": [wrapper]}]))
        self.assertEqual(resolved[0]["title"], "PR #42 review: comments on specific lines")
        self.assertIn("Space o", resolved[0]["body"])
        self.assertEqual(resolved[0]["author"], "reviewer")
        written = dict(wrapper, body="Mostly good, two nits")
        events = ticket_activity(Ticket("DEMO-42", prs=[{"number": 42, "reviews": [written], "unresolved": [inline]}]))
        self.assertIn(("PR #42 review: commented", "Mostly good, two nits"), [(e["title"], e["body"]) for e in events])

    def test_jira_status_and_assignee_changes_are_events(self):
        ticket = Ticket("APP-42", jira_changes=[
            {"at": "2026-10-28T10:00:00-03:00", "field": "status", "from": "In Dev", "to": "In Code Review", "author": "Dev"},
            {"at": "2026-10-28T10:01:00-03:00", "field": "assignee", "from": "Dev", "to": "Rae", "author": "Dev"},
            {"at": "2026-10-29T09:00:00-03:00", "field": "assignee", "from": "Rae", "to": None, "author": "Rae"},
            {"at": "not a date", "field": "status", "from": "A", "to": "B"}])
        events = ticket_activity(ticket)
        self.assertEqual([(e["source"], e["title"], e["author"]) for e in events], [
            ("Jira", "Unassigned (was Rae)", "Rae"),
            ("Jira", "Assigned to Rae (was Dev)", "Dev"),
            ("Jira", "Moved In Dev → In Code Review", "Dev")])

    def test_no_external_events_means_an_empty_log(self):
        ticket = Ticket("DEMO-42")
        ticket.local = {"last_local_activity_at": "2026-10-27T13:00:00Z"}
        self.assertEqual(ticket_activity(ticket), [])

    def test_jira_helper_loads_recent_comment_text_and_timestamps_only_when_requested(self):
        from sidequest.jira import client
        issue = {'key': 'DEMO-42', 'fields': {'summary': 'Check totals', 'status': {'name': 'In QA'}}}
        comments = {'total': 1, 'comments': [{'author': {'displayName': 'Reviewer'},
                    'body': {'type': 'doc', 'content': [{'type': 'text', 'text': 'Check quantities'}]},
                    'created': '2026-10-27T12:00:00Z', 'updated': '2026-10-27T12:00:00Z'}]}
        def response(method, path, *args):
            return comments if '/comment?' in path else {'values': [], 'isLast': True} if '/changelog?' in path else issue
        with patch.object(client, 'jira', side_effect=response):
            result = client.fetch_one('DEMO-42', include_activity=True)
        self.assertEqual(result['jira_comments'][0]['body'], 'Check quantities')
        self.assertEqual(result['jira_comment_total'], 1)
        with patch.object(client, 'jira', return_value=issue) as request:
            result = client.fetch_one('DEMO-42')
        self.assertEqual(request.call_count, 1)
        self.assertNotIn('jira_comments', result)


if __name__ == "__main__":
    unittest.main()
