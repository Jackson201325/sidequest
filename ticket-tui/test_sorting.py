import unittest
from pathlib import Path

from core import Store, Ticket
from sorting import activity_date, last_commit, ordered
from tui import App


class SortingTests(unittest.TestCase):
    def test_dates_order_actual_instants_and_leave_missing_last_in_both_directions(self):
        first = Ticket("DEMO-1", updated="2026-10-27T14:00:00-03:00")
        later = Ticket("DEMO-2", updated="2026-10-27T18:00:00Z")
        missing = Ticket("DEMO-3", updated="not a date")
        self.assertEqual([t.key for t in ordered([first, later, missing], "Last Jira update")], ["DEMO-2", "DEMO-1", "DEMO-3"])
        self.assertEqual([t.key for t in ordered([missing, first, later], "Last Jira update", False)], ["DEMO-1", "DEMO-2", "DEMO-3"])

    def test_comment_sort_uses_comment_dates_and_not_generic_activity_or_bodyless_approval(self):
        ticket = Ticket("DEMO-1", prs=[{
            "updated_at": "2026-11-01T12:00:00Z",
            "discussion": [{"createdAt": "2026-10-25T12:00:00Z"}],
            "reviews": [{"submittedAt": "2026-10-29T12:00:00Z", "body": ""}],
            "unresolved": [{"comments": [{"created_at": "2026-10-27T12:00:00Z"}]}],
        }])
        self.assertTrue(activity_date(ticket, "Last GitHub comment").startswith("2026-10-27"))
        self.assertIsNone(activity_date(Ticket("DEMO-2", prs=[{"updated_at": "2026-11-01T12:00:00Z"}]), "Last GitHub comment"))

    def test_last_commit_uses_git_and_pr_commits_and_nothing_else(self):
        ticket = Ticket("DEMO-1", updated="2026-11-01T12:00:00Z", local={"progress_at": "2026-11-01T12:00:00Z"},
                        prs=[{"updated_at": "2026-11-01T12:00:00Z", "commits": [{"authoredDate": "2026-10-28T12:00:00Z"}]}])
        worklog = {"entries": {"DEMO-1": [{"date": "2026-10-27T12:00:00Z"}]}}
        self.assertTrue(activity_date(ticket, "Last commit", worklog).startswith("2026-10-28"))
        self.assertIsNone(last_commit(Ticket("DEMO-2", updated="2026-11-01T12:00:00Z")))
        newer, older, none = Ticket("DEMO-3"), Ticket("DEMO-4"), Ticket("DEMO-5")
        worklog = {"entries": {"DEMO-3": [{"date": "2026-10-27T15:00:00Z"}], "DEMO-4": [{"date": "2026-10-20T15:00:00Z"}]}}
        self.assertEqual([t.key for t in ordered([none, older, newer], "Last commit", True, worklog)], ["DEMO-3", "DEMO-4", "DEMO-5"])

    def test_old_saved_sort_name_maps_to_last_commit(self):
        store = Store(":memory:")
        try:
            store.save("@app", {"sort_mode": "Last work date", "sort_descending": True})
            self.assertEqual(App(store, Path("/tmp"), demo=True).sort_mode, "Last commit")
        finally:
            store.close()

    def test_longest_waiting_orders_hours_within_the_same_business_day(self):
        from datetime import datetime
        from core import TZ, rank
        store = Store(":memory:")
        self.addCleanup(store.close)
        shorter, longer = Ticket("DEMO-1"), Ticket("DEMO-2")
        rank(shorter, store, datetime(2026, 10, 26, 11, tzinfo=TZ))
        rank(longer, store, datetime(2026, 10, 26, 9, tzinfo=TZ))
        for ticket in (shorter, longer):
            rank(ticket, store, datetime(2026, 10, 26, 16, tzinfo=TZ))
        self.assertEqual(ordered([shorter, longer], "Longest waiting"), [longer, shorter])
        self.assertEqual(ordered([longer, shorter], "Longest waiting", False), [shorter, longer])

    def test_priority_waiting_and_ticket_order(self):
        low = Ticket("DEMO-2", priority="Low", age=3)
        high = Ticket("DEMO-10", priority="High", age=1)
        self.assertEqual(ordered([low, high], "Priority")[0], high)
        self.assertEqual(ordered([low, high], "Longest waiting")[0], low)
        self.assertEqual(ordered([high, low], "Ticket", False)[0], low)

    def test_priority_keeps_waiting_below_actionable_work_in_both_directions(self):
        low = Ticket("DEMO-1", priority="Low", lane="Needs me")
        high = Ticket("DEMO-2", priority="High", lane="Needs me")
        clarify = Ticket("DEMO-3", priority="Medium", lane="Clarify")
        unknown = Ticket("DEMO-4", lane="Needs me")
        waiting = Ticket("DEMO-5", priority="Highest", lane="Waiting")
        tickets = [waiting, unknown, low, clarify, high]
        self.assertEqual(ordered(tickets, "Priority"), [high, clarify, low, unknown, waiting])
        self.assertEqual(ordered(tickets, "Priority", False), [low, clarify, high, unknown, waiting])
        self.assertEqual(ordered([waiting], "Priority"), [waiting])

    def test_attention_keeps_old_waits_below_actionable_work_even_when_reversed(self):
        mine = Ticket("DEMO-1", lane="Needs me", score=65)
        clarify = Ticket("DEMO-2", lane="Clarify", score=30)
        waiting = Ticket("DEMO-3", lane="Waiting", score=85, age=10)
        self.assertEqual(ordered([waiting, clarify, mine], "Attention"), [mine, clarify, waiting])
        self.assertEqual(ordered([waiting, clarify, mine], "Attention", False), [clarify, mine, waiting])

    def test_sort_persists_and_removed_explanations_stay_out_of_views(self):
        store = Store(":memory:")
        try:
            app = App(store, Path("/tmp"), demo=True)
            app.set_sort("Last GitHub comment", False)
            app = App(store, Path("/tmp"), demo=True)
            self.assertEqual(app.sort_mode, "Last GitHub comment")
            self.assertFalse(app.sort_descending)
            for view in ("Overview", "Workflow"):
                app.detail_tab = view
                text = "\n".join(app.details(app.selected()))
                self.assertNotIn("WHY THIS STAGE", text)
                self.assertNotIn("WHY YOU ARE HERE", text)
                self.assertNotIn("WHY THIS NEEDS ATTENTION", text)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
