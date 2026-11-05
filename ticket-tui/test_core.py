import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from core import Store, TZ, Ticket, business_days, infer, rank, tickets_from


class SignalHistoryTests(unittest.TestCase):
    def test_clock_reset_records_what_changed(self):
        store = Store(":memory:")
        try:
            pr = {"number": 2040, "review_decision": "", "requested_reviewers": ["example-org"]}
            rank(Ticket("DEMO-297", "T", prs=[pr]), store, clock=datetime(2026, 10, 28, 10, tzinfo=TZ))
            rank(Ticket("DEMO-297", "T", status="Ready for QA", prs=[pr]), store,
                 clock=datetime(2026, 10, 28, 11, tzinfo=TZ))
            messages = [m for _, m in store.history("DEMO-297")]
            self.assertEqual(messages[-1], "First observed state")
            self.assertIn("status Unknown → Ready for QA", messages[0])
        finally:
            store.close()

    def test_flip_and_flip_back_keeps_the_original_clock(self):
        store = Store(":memory:")
        try:
            calm = {"number": 2040, "review_decision": "", "requested_reviewers": ["example-org"]}
            wobble = {**calm, "requested_reviewers": []}              # momentarily "Arrange a reviewer"
            at = lambda h, m=0: datetime(2026, 10, 28, h, m, tzinfo=TZ)
            rank(Ticket("DEMO-297", "T", prs=[calm]), store, clock=at(9))
            rank(Ticket("DEMO-297", "T", prs=[wobble]), store, clock=at(16, 19))
            ticket = rank(Ticket("DEMO-297", "T", prs=[calm]), store, clock=at(16, 20))
            self.assertEqual(store.get("DEMO-297")["observed_since"], at(9).isoformat())
            self.assertEqual(ticket.wait_label, "7h")
            self.assertTrue(store.history("DEMO-297")[0][1].startswith("Flip back ignored"))
            # A real change that sticks still restarts the clock.
            later = rank(Ticket("DEMO-297", "T", status="Ready for QA", prs=[calm]), store, clock=at(16, 30))
            self.assertEqual(later.wait_label, "<1h")
        finally:
            store.close()


class AttentionTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.friday = datetime(2026, 10, 23, 10, tzinfo=TZ)
        self.monday = datetime(2026, 10, 26, 10, tzinfo=TZ)
        self.wednesday = datetime(2026, 10, 28, 10, tzinfo=TZ)

    def tearDown(self):
        self.store.close()

    def waiting(self):
        return Ticket("DEMO-42", "Inventory totals", prs=[
            {"number": 42, "requested_reviewers": ["reviewer"], "ci": "green"}])

    def test_business_days_ignore_weekend(self):
        self.assertEqual(business_days(self.friday, self.monday), 1)
        self.assertEqual(business_days(self.friday, self.wednesday), 3)
        self.assertEqual(business_days(self.monday, self.friday), 0)

    def test_first_observation_does_not_invent_age(self):
        ticket = self.waiting()
        ticket.prs[0]["updated_at"] = "2020-01-01T00:00:00Z"
        rank(ticket, self.store, self.monday)
        self.assertEqual(ticket.age, 0)
        self.assertEqual(ticket.lane, "Waiting")

    def test_waiting_gains_pressure_and_activity_does_not_reset_it(self):
        ticket = self.waiting()
        rank(ticket, self.store, self.friday)
        ticket.prs[0]["updated_at"] = self.wednesday.isoformat()
        rank(ticket, self.store, self.wednesday)
        self.assertEqual(ticket.age, 3)
        self.assertEqual(ticket.lane, "Waiting")

    def test_old_local_overrides_are_ignored(self):
        ticket = self.waiting()
        rank(ticket, self.store, self.friday)
        self.store.save(ticket.key, {"court": "me", "action": "Old note", "followup": self.friday.isoformat(),
                                     "progress_at": self.wednesday.isoformat()})
        rank(ticket, self.store, self.wednesday)
        self.assertEqual((ticket.court, ticket.lane, ticket.action, ticket.age),
                         ("them", "Waiting", "Follow up on review", 3))

    def test_requested_changes_override_review_waiting(self):
        ticket = self.waiting()
        rank(ticket, self.store, self.friday)
        ticket.prs[0]["review_decision"] = "CHANGES_REQUESTED"
        rank(ticket, self.store, self.wednesday)
        self.assertEqual(ticket.court, "me")
        self.assertEqual(ticket.lane, "Needs me")
        self.assertEqual(ticket.age, 0)

    def test_approval_and_qa_assignment_are_not_assumed_ready(self):
        self.assertEqual(infer(Ticket("DEMO-1", prs=[{"review_decision": "APPROVED"}]))[0], "unknown")
        self.assertEqual(infer(Ticket("DEMO-2", status="QA", assigned_me=True))[0], "unknown")

    def test_fresh_empty_sources_do_not_resurrect_old_work(self):
        fallback = {"jira_assigned": [{"key": "DEMO-1"}], "open_prs": [{"number": 1}]}
        self.assertEqual(tickets_from({"tickets": []}, {"open_prs": []}, fallback), [])

    def test_branch_links_unkeyed_pr_and_keeps_multiple_prs(self):
        prs = {"open_prs": [{"number": 1, "branch": "fix/DEMO-42-stock"},
                             {"number": 2, "ticket": "DEMO-42"}, {"number": 3}]}
        tickets = tickets_from({}, prs, worktrees={"DEMO-42": "/tmp/example"})
        self.assertEqual([t.key for t in tickets], ["DEMO-42", "PR-3"])
        self.assertEqual(len(tickets[0].prs), 2)
        self.assertEqual(tickets[0].worktree, "/tmp/example")

    def test_state_survives_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "state.sqlite3"
            first = Store(path)
            first.save("DEMO-42", {"note": "Check totals"}, "Added note", self.friday)
            first.close()
            second = Store(path)
            self.assertEqual(second.get("DEMO-42")["note"], "Check totals")
            self.assertEqual(len(second.history("DEMO-42")), 1)
            second.close()


if __name__ == "__main__":
    unittest.main()
