"""Detail tabs as styled rows, and paging from the terminal size, without curses."""
import os
import sys
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
from core import Store, Ticket, now
from detail_views import DetailViews, Row, wrap
from queue_evidence import QueueEvidence
from test_responsive import Screen
from tui import App


class DetailViewTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.evidence = QueueEvidence(self.store, self.root)
        self.views = DetailViews(self.evidence)

    def rows(self, tab, ticket, **extra):
        return self.views.rows(tab, ticket, plans=self.root, **extra)

    def styled(self, rows, style):
        return [row.text for row in rows if row.style == style]

    def test_overview_marks_its_headings_and_current_step_as_data(self):
        ticket = Ticket("APP-1", "Totals", status="QA")
        rows = self.rows("Overview", ticket)
        self.assertEqual(self.styled(rows, "heading"), ["STATUS", "DATES", "HEROKU ENVIRONMENT", "WORKSPACE"])
        self.assertEqual(self.styled(rows, "current"), ["YOU ARE HERE: QA testing (step 4 of 6)"])
        self.assertNotIn("APP-1", [row.text for row in rows[:2]], "the panel border already shows key and title")

    def test_flow_marks_the_current_step_from_the_stage_not_the_text(self):
        rows = self.rows("Workflow", Ticket("APP-1", "Totals", status="Code Review"))
        self.assertEqual(self.styled(rows, "current"), ["YOU ARE HERE: Code review (step 3 of 6)",
                                                        "3. Code review   YOU ARE HERE"])
        self.assertIn("WORKFLOW", self.styled(rows, "heading"))

    def test_activity_rows_mark_days_events_and_snippets(self):
        clock = now()
        ticket = Ticket("APP-1", "Totals", updated=(clock - timedelta(hours=1)).isoformat(),
                        jira_comments=[{"author": "Rae", "body": "Off by a cent", "created_at": clock.isoformat(),
                                        "updated_at": clock.isoformat()}])
        rows = self.rows("Activity", ticket)
        self.assertTrue(self.styled(rows, "day"))
        self.assertEqual(len(self.styled(rows, "event")), 2)
        self.assertTrue(any("Off by a cent" in text for text in self.styled(rows, "dim")))

    def test_plan_headings_are_styled_without_a_hidden_marker_and_cached_until_edited(self):
        ticket = Ticket("APP-1", "Totals")
        path = self.root / "APP-1" / "plan.md"
        path.parent.mkdir()
        path.write_text("# Plan\n## Approach\nValidate inputs.\n")
        rows = self.rows("Plan", ticket)
        self.assertEqual(self.styled(rows, "heading"), ["PLAN", "APPROACH"])
        self.assertFalse(any("\x00" in row.text for row in rows))
        path.write_text("# Changed\n")
        os.utime(path, (1, 1))
        self.assertEqual(self.styled(self.rows("Plan", ticket), "heading"), ["CHANGED"])

    def test_standup_marks_section_titles(self):
        data_rows = self.views.standup_rows(["STANDUP PREVIEW", "Yesterday:", "- did a thing", "Today:"])
        self.assertEqual(self.styled(data_rows, "heading"), ["STANDUP PREVIEW", "Yesterday:", "Today:"])

    def test_refresh_errors_come_first(self):
        self.evidence.finish_refresh(({}, ["GitHub: login unavailable or expired."], {"prs"}))
        rows = self.rows("Overview", None)
        self.assertEqual([row.text for row in rows[:2]], ["REFRESH ERROR (cached data)", "GitHub: login unavailable or expired."])

    def test_environment_reports_cached_refreshing_and_missing_states(self):
        ticket = Ticket("APP-1", "Totals")
        self.assertEqual(self.views.environment(ticket, loading=False), "No linked PR")
        ticket.prs = [{"number": 7}]
        self.assertEqual(self.views.environment(ticket, loading=True), "Loading")
        self.evidence.apply("heroku", {"entries": {"7": {"status": "Web up", "checked_at": now().isoformat()}}})
        self.assertEqual(self.views.environment(ticket, loading=False), "Web up")
        self.assertEqual(self.views.environment(ticket, loading=True), "Web up (refreshing)")

    def test_wrapping_keeps_styles_and_indents_event_continuations(self):
        rows = wrap([Row("STATUS", "heading"), Row("09:00 Jira ✎ " + "word " * 20, "event"),
                     Row("  - nested " + "item " * 12, "plain")], 30)
        self.assertEqual(rows[0], Row("STATUS", "heading"))
        self.assertEqual(rows[1].style, "event")
        self.assertTrue(rows[2].text.startswith(" " * 13) and rows[2].style == "dim")
        nested = [row for row in rows if "item" in row.text]
        self.assertTrue(all(row.text.startswith("  ") for row in nested))


class ViewportTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = Store(":memory:")
        self.addCleanup(self.store.close)
        self.app = App(self.store, Path(folder.name), demo=True)

    def test_paging_comes_from_the_terminal_size(self):
        self.app.screen = Screen(18, 80)
        small = self.app.viewport()
        self.app.screen = Screen(40, 120)
        large = self.app.viewport()
        self.assertLess(small.list_rows, large.list_rows)
        self.assertLess(small.detail_rows, large.detail_rows)

    def test_page_keys_use_the_viewport_and_draw_changes_no_navigation_state(self):
        self.app.screen = Screen(18, 80)
        rows = self.app.viewport().list_rows
        self.app.press("\x06")
        self.assertEqual(self.app.index, min(rows, len(self.app.visible()) - 1))
        state = (self.app.index, self.app.offset, self.app.preview_scroll)
        self.app.draw()
        self.assertEqual(state, (self.app.index, self.app.offset, self.app.preview_scroll))

    def test_fit_keeps_the_selection_visible_and_scroll_in_range(self):
        self.app.screen = Screen(18, 80)
        self.app.index, self.app.offset, self.app.preview_scroll = len(self.app.visible()) - 1, 0, 10_000
        self.app.fit()
        view = self.app.viewport()
        self.assertTrue(self.app.offset <= self.app.index < self.app.offset + view.list_rows)
        self.assertLessEqual(self.app.preview_scroll, max(0, len(view.detail_lines) - view.detail_rows))


if __name__ == "__main__":
    unittest.main()
