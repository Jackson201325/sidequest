"""Grouped, borderless ticket list (redesign phase 2, specs/tui-redesign-inbox.md)."""
import unittest
from pathlib import Path

from core import Store, Ticket
from layout import group_rows, inbox_columns, inbox_row, list_offset, title_rule
from test_responsive import Screen
from tui import App

BOXES = ("┏", "┗", "╭", "╰", "┃")


def tickets():
    return [Ticket("DEMO-1", "Mine", lane="Needs me"), Ticket("DEMO-2", "Also mine", lane="Needs me"),
            Ticket("DEMO-3", "Unclear", lane="Clarify"), Ticket("DEMO-4", "Theirs", lane="Waiting")]


class GroupTests(unittest.TestCase):
    def test_grouped_lines_put_a_heading_before_each_lane(self):
        self.assertEqual(group_rows(tickets(), True), [
            ("heading", "NEEDS YOU 2", "Needs me"), ("ticket", 0), ("ticket", 1),
            ("heading", "UNCLEAR 1", "Clarify"), ("ticket", 2),
            ("heading", "WAITING ON OTHERS 1", "Waiting"), ("ticket", 3)])

    def test_single_lane_lists_have_no_headings(self):
        self.assertEqual(group_rows(tickets(), False), [("ticket", i) for i in range(4)])

    def test_offset_keeps_the_selection_and_its_heading_on_screen(self):
        lines = group_rows(tickets(), True)
        self.assertEqual(list_offset(lines, 0, 0, 3), 0)
        self.assertEqual(list_offset(lines, 3, 0, 3), 4)       # DEMO-4 is display line 6
        self.assertEqual(list_offset(lines, 2, 4, 3), 3)       # back up to UNCLEAR's heading
        self.assertEqual(list_offset(lines, 1, 0, 3), 0)


class RowTests(unittest.TestCase):
    def text(self, parts):
        return "".join(text for text, _ in parts)

    def test_row_fills_the_width_with_glyph_key_title_tag_wait_agent(self):
        mine = Ticket("DEMO-1", "Validate bulk request quantities", lane="Needs me",
                      prs=[{"number": 9, "ci": "green", "review_decision": "CHANGES_REQUESTED"}])
        cols = inbox_columns(80)
        parts = inbox_row(mine, cols, agent="working")
        self.assertEqual(len(self.text(parts)), sum(cols.values()))
        self.assertEqual(parts[0], ("● ", "Needs me"))
        self.assertIn(("✗ changes", "bad"), [(t.strip(), s) for t, s in parts])
        self.assertIn(("✦", "agent"), [(t.strip(), s) for t, s in parts])

    def test_waiting_rows_name_the_owner_and_age_past_the_reminder(self):
        theirs = Ticket("DEMO-2", "Theirs", status="In QA", court="them", assignee="QA Reviewer",
                        lane="Waiting", age=6)
        parts = [(t.strip(), s) for t, s in inbox_row(theirs, inbox_columns(80), stale_days=2)]
        self.assertIn(("QA", "waiting"), parts)
        self.assertEqual(parts[-2][1], "aging")
        self.assertEqual(parts[2][1], "waiting")                # their titles are dim

    def test_date_sorts_show_when_instead_of_the_tag(self):
        mine = Ticket("DEMO-1", "Title", lane="Needs me", prs=[{"number": 9, "ci": "failing"}])
        text = self.text(inbox_row(mine, inbox_columns(80, with_when=True), when="3h"))
        self.assertIn("3h", text)
        self.assertNotIn("✗ CI", text)

    def test_title_rule_marks_focus_with_an_arrow(self):
        focused, other = title_rule(40, "Tickets 4", True, "1–4 of 9"), title_rule(40, "Tickets 4", False)
        self.assertTrue(focused.startswith("▸ Tickets 4 ─"))
        self.assertTrue(focused.endswith(" 1–4 of 9 ─"))
        self.assertTrue(other.startswith("  Tickets 4 ─"))
        self.assertEqual((len(focused), len(other)), (40, 40))


class ScreenTests(unittest.TestCase):
    def setUp(self):
        self.store = Store(":memory:")
        self.app = App(self.store, Path("/tmp"), demo=True)
        self.app.screen = Screen(32, 119)                 # stacked; test_side_by_side covers wider

    def tearDown(self):
        self.store.close()

    def test_all_lists_tickets_by_group_whatever_the_sort(self):
        rank = {"Needs me": 0, "Clarify": 1, "Waiting": 2}
        for mode in ("Attention", "Last Jira update", "Ticket", "Longest waiting"):
            with self.subTest(mode=mode):
                self.app.sort_mode = mode
                self.app.rebuild()
                lanes = [rank[t.lane] for t in self.app.visible()]
                self.assertEqual(lanes, sorted(lanes))

    def test_screen_has_title_rules_and_group_headings_but_no_boxes(self):
        self.app.draw()
        lines = self.app.screen.lines
        screen = "\n".join(lines)
        self.assertTrue(lines[1].startswith("▸ Tickets 4 "))
        self.assertIn("NEEDS YOU 1", lines[2])
        self.assertIn("DEMO-901", lines[3])
        for heading in ("UNCLEAR 1", "WAITING ON OTHERS 2"):
            self.assertIn(heading, screen)
        self.assertFalse(any(box in screen for box in BOXES))
        preview = next(line for line in lines if "DEMO-901 · Validate" in line)
        self.assertTrue(preview.startswith("  DEMO-901 · "))
        self.app.press("l")
        self.app.draw()
        lines = self.app.screen.lines
        self.assertTrue(lines[1].startswith("  Tickets 4 "))
        self.assertTrue(any(line.startswith("▸ DEMO-901 · ") for line in lines))

    def test_moving_down_follows_the_groups(self):
        keys = [self.app.selected().key]
        for _ in range(3):
            self.app.press("j")
            keys.append(self.app.selected().key)
        self.assertEqual(keys, ["DEMO-901", "DEMO-904", "DEMO-902", "DEMO-903"])

    def test_one_lane_views_have_no_headings(self):
        self.app.press("3")
        self.app.draw()
        screen = "\n".join(self.app.screen.lines)
        self.assertNotIn("WAITING ON OTHERS", screen)
        self.assertIn("DEMO-902", self.app.screen.lines[2])


if __name__ == "__main__":
    unittest.main()
