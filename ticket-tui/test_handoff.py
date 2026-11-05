import unittest
from core import Store, Ticket, rank
from workflow import next_owner, stage_context

class HandoffTests(unittest.TestCase):
    def test_review_handoff_keeps_jira_owner_despite_github_feedback(self):
        store = Store(':memory:')
        self.addCleanup(store.close)
        for status in ('Ready for Code Review', 'In Code Review', 'In QA', 'Approved'):
            for pr in ({'review_decision': 'CHANGES_REQUESTED'}, {'ci': 'failing'}, {'unresolved_count': 2}):
                with self.subTest(status=status, pr=pr):
                    ticket = Ticket('DEMO-600', status=status, assignee='Review Owner', assigned_me=False,
                                    prs=[{'number': 2059, 'requested_reviewers': ['example-org'], **pr}])
                    rank(ticket, store)
                    self.assertEqual(ticket.court, 'them')
                    self.assertEqual(next_owner(ticket), 'Review Owner')
        self.assertEqual(stage_context(Ticket('DEMO-600', status='In Code Review'))['index'], 2)

class StatusAgeTests(unittest.TestCase):
    def test_jira_transition_sets_age_on_first_load_and_pr_changes_do_not_reset_it(self):
        from datetime import datetime
        from core import TZ, tickets_from
        store = Store(':memory:')
        self.addCleanup(store.close)
        jira = {'tickets': [{'key': 'DEMO-600', 'status': 'In Code Review', 'assignee': 'Review Owner',
                'assignee_ok': False, 'status_since': '2026-10-23T10:00:00-03:00'}]}
        ticket = tickets_from(jira, {'open_prs': []})[0]
        rank(ticket, store, datetime(2026, 10, 26, 11, tzinfo=TZ))
        self.assertEqual(ticket.wait_label, '1d 1h')
        ticket.prs = [{'number': 2059, 'review_decision': 'CHANGES_REQUESTED'}]
        rank(ticket, store, datetime(2026, 10, 26, 12, tzinfo=TZ))
        self.assertEqual(ticket.wait_label, '1d 2h')
        self.assertEqual(ticket.wait_source, 'Jira status transition')

    def test_wait_cannot_predate_first_assignment_and_later_status_still_wins(self):
        from datetime import datetime
        from core import TZ, tickets_from
        store = Store(':memory:')
        self.addCleanup(store.close)
        issue = {'key': 'DEMO-42', 'status': 'In Dev', 'assignee': 'Example Developer', 'assignee_ok': True,
                 'status_since': '2026-09-01T09:00:00-03:00', 'first_assigned_at': '2026-10-28T10:00:00-03:00'}
        ticket = tickets_from({'tickets': [issue]}, {'open_prs': []})[0]
        rank(ticket, store, datetime(2026, 10, 29, 10, tzinfo=TZ))
        self.assertEqual(ticket.wait_label, '1d')
        self.assertEqual(ticket.wait_source, 'First Jira assignment to you')
        self.assertEqual(ticket.wait_since, issue['first_assigned_at'])
        ticket.status_since = '2026-10-29T09:00:00-03:00'
        rank(ticket, store, datetime(2026, 10, 29, 10, tzinfo=TZ))
        self.assertEqual(ticket.wait_label, '1h')
        self.assertEqual(ticket.wait_source, 'Jira status transition')
