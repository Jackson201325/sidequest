import unittest
from datetime import datetime, timedelta

from core import TZ, Ticket
from layout import HEAVY, LIGHT, border, card, inbox_columns, inbox_row, lane_tab, scroll_label, pr_label, relative, timeline, turn_label


def row_text(ticket, width=90):
    return "".join(text for text, _ in inbox_row(ticket, inbox_columns(width)))


class LayoutTests(unittest.TestCase):
    def test_card_adds_branch_state_and_qa_hint_before_the_next_step(self):
        ticket = Ticket("DEMO-1", court="me", lane="Needs me", action="Continue implementation")
        lines = card(ticket, self.clock, local=["Local 2 uncommitted · QA shots missing"],
                     hint="QA shots missing: Space s → QA locally")
        self.assertEqual(lines[-3:], ["Local 2 uncommitted · QA shots missing", "→ Continue implementation",
                                      "→ QA shots missing: Space s → QA locally"])

    clock = datetime(2026, 10, 27, 16, 0, tzinfo=TZ)

    def test_relative_times(self):
        cases = [(timedelta(seconds=30), "now"), (timedelta(minutes=5), "5m"), (timedelta(hours=3), "3h"),
                 (timedelta(days=2), "2d"), (timedelta(days=21), "3w"), (timedelta(days=90), "3mo")]
        for delta, text in cases:
            self.assertEqual(relative(self.clock - delta, self.clock), text)
        self.assertEqual(relative("not a date", self.clock), "")
        self.assertEqual(relative((self.clock - timedelta(hours=1)).isoformat(), self.clock), "1h")

    def test_turn_and_pr_labels_are_short(self):
        mine = Ticket("DEMO-1", court="me")
        review = Ticket("DEMO-2", status="Code Review", court="them",
                        prs=[{"number": 7, "ci": "failing", "requested_reviewers": ["example-org", "miguel"]}])
        qa = Ticket("DEMO-3", status="In QA", court="them", assignee="QA Reviewer")
        self.assertEqual(turn_label(mine), "you")
        self.assertEqual(turn_label(review), "example-org +1")
        self.assertEqual(turn_label(qa), "QA")
        self.assertEqual(turn_label(Ticket("DEMO-4", court="unknown")), "?")
        self.assertEqual(pr_label(review), "#7 ✗")
        self.assertEqual(pr_label(Ticket("DEMO-5", prs=[{"number": 1, "ci": "green"}, {"number": 2}])), "#1 ✓ +1")
        self.assertEqual(pr_label(mine), "—")

    def test_narrow_rows_drop_the_tag_and_keep_a_title(self):
        cols = inbox_columns(34)
        self.assertEqual(cols["tag"], 0)
        self.assertGreaterEqual(cols["title"], 8)
        ticket = Ticket("DEMO-123", "A very long ticket title that will not fit in the column", lane="Needs me")
        self.assertIn("…", row_text(ticket, 60))
        self.assertEqual(len(row_text(ticket, 60)), sum(inbox_columns(60).values()))

    def test_focus_is_visible_by_border_shape(self):
        focused, other = border(20, "Tickets 3", True), border(20, "Tickets 3", False)
        self.assertTrue(focused.startswith(HEAVY[0]) and other.startswith(LIGHT[0]))
        self.assertEqual(len(focused), 20)
        self.assertIn(" Tickets 3 ", focused)
        self.assertEqual(border(20, "", True, top=False), HEAVY[4] + HEAVY[1] * 18 + HEAVY[5])

    def test_card_summarises_lane_pr_dates_and_next_step(self):
        ticket = Ticket("DEMO-9", "Title", status="Code Review", court="them", lane="Waiting", age=3,
                        updated=(self.clock - timedelta(hours=3)).isoformat(), action="Wait for review",
                        prs=[{"number": 12, "ci": "green", "review_decision": "CHANGES_REQUESTED",
                              "unresolved_count": 2, "requested_reviewers": ["example-org"]}])
        lines = card(ticket, self.clock, self.clock - timedelta(days=2), "Web up", stale_days=2)
        self.assertEqual(lines[0], "○ Waiting · Code review · turn: example-org · waiting 3d · chase it")
        self.assertEqual(lines[1], "PR #12 ✓ CI green · changes requested · 2 unresolved")
        self.assertEqual(lines[2], "Jira Code Review · updated 3h · last commit 2d · Heroku Web up")
        self.assertEqual(lines[3], "→ Wait for review")
        self.assertEqual(card(Ticket("DEMO-1", court="me", lane="Needs me"), self.clock)[1], "PR none yet")

    def test_timeline_groups_by_day_with_marks_and_snippets(self):
        at = lambda **kw: (self.clock - timedelta(**kw)).isoformat()
        events = [{"at": at(hours=1), "source": "GitHub", "title": "PR #12 review: approved", "body": "", "author": "reviewer"},
                  {"at": at(hours=2), "source": "Jira", "title": "Comment added", "body": "Line one\n\n  line two",
                   "author": "QA"},
                  {"at": at(days=1), "source": "GitHub", "title": "PR #12 commit abc1234", "body": "Fix", "author": ""}]
        lines = timeline(events, self.clock)
        self.assertEqual(lines[0], "── Today")
        self.assertEqual(lines[1], "15:00 GH   ✓ PR #12 review: approved · reviewer")
        self.assertEqual(lines[2], "14:00 Jira ✎ Comment added · QA")
        self.assertEqual(lines[3].strip(), "Line one line two")
        self.assertEqual(lines[5:7], ["── Yesterday", "16:00 GH   • PR #12 commit abc1234"])

    def test_scroll_labels_and_compact_tabs(self):
        self.assertEqual(scroll_label(0, 10, 8), "")
        self.assertEqual(scroll_label(3, 10, 31), " 4–13 of 31 ")
        bottom = border(30, "", False, top=False, label=" 4–13 of 31 ")
        self.assertEqual(len(bottom), 30)
        self.assertTrue(bottom.endswith(" 4–13 of 31 ─╯"))
        self.assertEqual(lane_tab(3, "Waiting", 2, False, True), " 3 ○ 2 ")
        self.assertEqual(lane_tab(3, "Waiting", 2, True, True), " 3 ○ Waiting 2 ")
        self.assertEqual(lane_tab(1, "All", 6, False, True), " 1 All 6 ")
        self.assertEqual(lane_tab(5, "In Dev", 3, False, True), " 5 ◆ 3 ")
        self.assertEqual(lane_tab(5, "In Dev", 3, True, True), " 5 ◆ In Dev 3 ")

    def test_wait_counts_only_weekday_office_hours_and_rolls_over(self):
        from core import Store, rank
        from datetime import timezone
        cases = [
            (datetime(2026, 10, 26, 9, tzinfo=TZ), datetime(2026, 10, 27, 16, tzinfo=TZ), "1d 7h", "Waiting"),
            (datetime(2026, 10, 26, 9, tzinfo=TZ), datetime(2026, 10, 27, 17, tzinfo=TZ), "2d", "Waiting"),
            (datetime(2026, 10, 23, 16, tzinfo=TZ), datetime(2026, 10, 26, 10, tzinfo=TZ), "2h", "Waiting"),
            (datetime(2026, 10, 26, 7, tzinfo=TZ), datetime(2026, 10, 26, 20, tzinfo=TZ), "1d", "Waiting"),
            (datetime(2026, 10, 24, 9, tzinfo=TZ), datetime(2026, 10, 25, 17, tzinfo=TZ), "<1h", "Waiting"),
            (datetime(2026, 10, 26, 12, tzinfo=timezone.utc), datetime(2026, 10, 26, 14, tzinfo=timezone.utc), "2h", "Waiting"),
            (datetime(2026, 10, 26, 9, tzinfo=TZ), datetime(2026, 10, 26, 9, 59, tzinfo=TZ), "<1h", "Waiting"),
            (datetime(2026, 10, 26, 10, tzinfo=TZ), datetime(2026, 10, 26, 9, tzinfo=TZ), "<1h", "Waiting"),
        ]
        for start, end, label, lane in cases:
            with self.subTest(start=start, end=end):
                store = Store(":memory:")
                self.addCleanup(store.close)
                ticket = Ticket("DEMO-42", "Validate totals", status="Code Review",
                                prs=[{"number": 42, "requested_reviewers": ["reviewer"], "ci": "green"}])
                rank(ticket, store, start)
                rank(ticket, store, end)
                self.assertIn(label, row_text(ticket))
                self.assertIn("observed wait " + label, card(ticket, end)[0])
                self.assertEqual(ticket.lane, lane)

    def test_escalation_uses_forty_working_hours_and_state_change_resets_hours(self):
        from core import Store, rank
        from standup import preview
        store = Store(":memory:")
        self.addCleanup(store.close)
        ticket = Ticket("DEMO-42", "Validate totals", status="Code Review",
                        prs=[{"number": 42, "requested_reviewers": ["reviewer"], "ci": "green"}])
        rank(ticket, store, datetime(2026, 10, 26, 9, tzinfo=TZ))
        clock = datetime(2026, 10, 30, 16, tzinfo=TZ)
        rank(ticket, store, clock)
        self.assertIn("4d 7h", row_text(ticket))
        self.assertEqual(preview([ticket], {}, clock)["blockers"], [])
        clock = clock.replace(hour=17)
        rank(ticket, store, clock)
        self.assertIn("waiting 5d business time", preview([ticket], {}, clock)["blockers"][0])
        ticket.prs[0]["review_decision"] = "CHANGES_REQUESTED"
        rank(ticket, store, clock)
        self.assertIn("<1h", row_text(ticket))
        self.assertEqual(ticket.age, 0)

    def test_top_table_wait_clock_advances_in_business_days(self):
        from core import Store, rank
        from datetime import datetime
        store = Store(":memory:")
        try:
            ticket = Ticket("DEMO-42", "Validate totals", status="Code Review",
                            prs=[{"number": 42, "requested_reviewers": ["reviewer"], "ci": "green"}])
            rank(ticket, store, datetime(2026, 10, 26, 10, tzinfo=TZ))
            self.assertIn("<1h", row_text(ticket))
            rank(ticket, store, datetime(2026, 10, 28, 10, tzinfo=TZ))
            self.assertIn("2d", row_text(ticket))
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
